"""
fetch_imagens.py — Busca imagens reais dos posts via API e injeta no dashboard
================================================================================

O que faz:
  1. Chama Instagram API → pega os top posts do período COM imagem (media_url)
  2. Chama Facebook API  → pega os top posts da página COM imagem
  3. Chama Meta Ads API  → pega thumbnails dos criativos COM imagem
  4. Atualiza SEED_DATA no dashboard-campanhas.html com as imagens em base64
  5. As imagens ficam embutidas no HTML — funciona offline, sem depender de URLs externas

Uso:
    python fetch_imagens.py                        # enriquece todos os períodos
    python fetch_imagens.py --periodo marco_2026   # apenas período específico
    python fetch_imagens.py --sem-ads              # só IG e FB, sem criativos Meta

Pré-requisito:
    meta_config.json preenchido com tokens reais
    pip install requests Pillow
"""

import json
import re
import sys
import os
import base64
import argparse
import requests
from datetime import datetime
from io import BytesIO

BASE = "https://graph.facebook.com/v20.0"
CONFIG_FILE = "meta_config.json"
DASHBOARD_FILE = "dashboard-campanhas.html"
MAX_IMG = 500        # px máximo para comprimir imagens de posts
MAX_LOGO = 300       # px máximo para thumbnails de criativos
JPEG_Q = 72          # qualidade JPEG

# ─────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────

def log(msg, level="INFO"):
    sym = {"INFO":"→","OK":"✓","WARN":"⚠","ERR":"✗","IMG":"🖼"}
    print(f"  {sym.get(level,'·')} {msg}")

def api(url, params):
    try:
        r = requests.get(url, params=params, timeout=30)
        d = r.json()
        if "error" in d:
            log(f"API erro: {d['error'].get('message','?')}", "ERR")
            return None
        return d
    except Exception as e:
        log(f"Conexão: {e}", "ERR")
        return None

def img_b64(url, max_px=MAX_IMG):
    """Baixa imagem, comprime e retorna data-URI base64."""
    if not url:
        return ""
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            return ""
        try:
            from PIL import Image
            img = Image.open(BytesIO(r.content)).convert("RGB")
            w, h = img.size
            if w > max_px or h > max_px:
                ratio = min(max_px/w, max_px/h)
                img = img.resize((int(w*ratio), int(h*ratio)), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=JPEG_Q)
            b64 = base64.b64encode(buf.getvalue()).decode()
            return f"data:image/jpeg;base64,{b64}"
        except ImportError:
            b64 = base64.b64encode(r.content).decode()
            ct = r.headers.get("content-type","image/jpeg")
            return f"data:{ct};base64,{b64}"
    except Exception as e:
        log(f"Falha img {url[:50]}…: {e}", "WARN")
        return ""

# ─────────────────────────────────────────────
# INSTAGRAM — TOP POSTS COM IMAGEM
# ─────────────────────────────────────────────

def ig_top_posts(token, ig_id, inicio, fim, limite=10):
    """Retorna lista dos top posts por alcance, com imagem embutida."""
    log(f"Instagram: buscando posts {inicio} → {fim}...")
    data = api(f"{BASE}/{ig_id}/media", {
        "fields": "id,timestamp,caption,like_count,comments_count,media_type,media_url,thumbnail_url,permalink",
        "since": inicio, "until": fim, "limit": 50,
        "access_token": token
    })
    if not data or "data" not in data:
        log("Instagram: nenhum post encontrado", "WARN")
        return []

    posts = []
    total = len(data["data"])
    log(f"Instagram: {total} posts encontrados — buscando métricas individuais...")

    for i, p in enumerate(data["data"]):
        p_reach = p_saved = p_shares = 0

        # Insights individuais do post
        ins = api(f"{BASE}/{p['id']}/insights", {
            "metric": "reach,saved,shares",
            "access_token": token
        })
        if ins and "data" in ins:
            for m in ins["data"]:
                v = m.get("values",[{}])[0].get("value",0) if m.get("values") else 0
                if m["name"]=="reach": p_reach=v
                elif m["name"]=="saved": p_saved=v
                elif m["name"]=="shares": p_shares=v

        tipo = p.get("media_type","IMAGE")
        tipo_label = "Reels" if tipo=="VIDEO" else "Carrossel" if tipo=="CAROUSEL_ALBUM" else "Feed"

        # URL da imagem (thumbnail para vídeo, media_url para foto)
        img_url = p.get("thumbnail_url") or p.get("media_url","")

        posts.append({
            "_rank": p_reach,
            "img": "",         # preenchido abaixo
            "_img_url": img_url,
            "caption": (p.get("caption") or "")[:150].replace("\n"," "),
            "alcance": p_reach,
            "curtidas": int(p.get("like_count",0)),
            "comentarios": int(p.get("comments_count",0)),
            "salvamentos": p_saved,
            "compartilhamentos": p_shares,
            "tipo": tipo_label
        })
        print(f"    [{i+1}/{total}] {tipo_label} — alcance {p_reach:,}", end="\r")

    print()
    # Ordenar por alcance e pegar top N
    posts.sort(key=lambda x: x["_rank"], reverse=True)
    top = posts[:limite]

    # Baixar imagens dos top posts
    log(f"Instagram: baixando imagens dos top {len(top)} posts...")
    for i, post in enumerate(top):
        url = post.pop("_img_url","")
        post.pop("_rank", None)
        if url:
            log(f"  [{i+1}/{len(top)}] {post['tipo']} — {post['caption'][:40]}…", "IMG")
            post["img"] = img_b64(url)
        else:
            post["img"] = ""

    log(f"Instagram: {len(top)} top posts com imagem prontos", "OK")
    return top

# ─────────────────────────────────────────────
# FACEBOOK — TOP POSTS COM IMAGEM
# ─────────────────────────────────────────────

def fb_top_posts(token, page_id, inicio, fim, limite=10):
    """Retorna lista dos top posts da página com imagem embutida."""
    log(f"Facebook: buscando posts {inicio} → {fim}...")

    # Precisa de Page Access Token — trocar User Token por Page Token
    page_token_data = api(f"{BASE}/{page_id}", {
        "fields": "access_token,name",
        "access_token": token
    })
    page_token = page_token_data.get("access_token", token) if page_token_data else token

    data = api(f"{BASE}/{page_id}/posts", {
        "fields": "id,message,created_time,attachments{media{image{src}},type}",
        "since": inicio, "until": fim, "limit": 30,
        "access_token": page_token
    })
    if not data or "data" not in data:
        log("Facebook: nenhum post encontrado", "WARN")
        return []

    posts = []
    total = len(data["data"])
    log(f"Facebook: {total} posts encontrados — buscando métricas...")

    for i, p in enumerate(data["data"]):
        p_reach = p_imp = p_clicks = 0

        ins = api(f"{BASE}/{p['id']}/insights", {
            "metric": "post_reach,post_impressions,post_clicks",
            "access_token": page_token
        })
        if ins and "data" in ins:
            for m in ins["data"]:
                v = m.get("values",[{}])[0].get("value",0) if m.get("values") else 0
                if m["name"]=="post_reach": p_reach=v
                elif m["name"]=="post_impressions": p_imp=v
                elif m["name"]=="post_clicks": p_clicks=v

        atts = p.get("attachments",{}).get("data",[{}])
        att = atts[0] if atts else {}
        img_url = att.get("media",{}).get("image",{}).get("src","")
        att_type = att.get("type","photo")
        tipo_label = "Reels" if att_type in ("video_autoplay","video_share") else \
                     "Carrossel" if att_type=="album" else "Feed"

        posts.append({
            "_rank": p_reach,
            "_img_url": img_url,
            "img": "",
            "caption": (p.get("message") or "")[:150].replace("\n"," "),
            "alcance": p_reach,
            "visualizacoes": p_imp,
            "cliques": p_clicks,
            "tipo": tipo_label
        })
        print(f"    [{i+1}/{total}] alcance {p_reach:,}", end="\r")

    print()
    posts.sort(key=lambda x: x["_rank"], reverse=True)
    top = posts[:limite]

    log(f"Facebook: baixando imagens dos top {len(top)} posts...")
    for i, post in enumerate(top):
        url = post.pop("_img_url","")
        post.pop("_rank",None)
        if url:
            log(f"  [{i+1}/{len(top)}] {post['tipo']} — {post['caption'][:40]}…", "IMG")
            post["img"] = img_b64(url)

    log(f"Facebook: {len(top)} posts com imagem prontos", "OK")
    return top

# ─────────────────────────────────────────────
# META ADS — CRIATIVOS COM THUMBNAIL
# ─────────────────────────────────────────────

def meta_criativos(token, ad_account_id, inicio, fim, limite=10):
    """Retorna top criativos por cliques com thumbnail do anúncio."""
    log("Meta Ads: buscando criativos...")
    data = api(f"{BASE}/{ad_account_id}/ads", {
        "fields": "name,creative{thumbnail_url,image_url,body,title},"
                  "insights.date_preset(last_30d){clicks,reach,impressions,cpc,cpm,spend,frequency}",
        "limit": 30,
        "access_token": token
    })
    if not data or "data" not in data:
        log("Meta Ads: nenhum criativo encontrado", "WARN")
        return []

    criativos = []
    for ad in data["data"]:
        cr = ad.get("creative",{})
        ins_list = ad.get("insights",{}).get("data",[{}])
        ins = ins_list[0] if ins_list else {}
        img_url = cr.get("thumbnail_url") or cr.get("image_url","")
        caption = cr.get("body") or cr.get("title") or ad.get("name","Criativo")
        if len(caption) > 120: caption = caption[:117]+"…"
        spend = float(ins.get("spend",0))
        clicks = int(ins.get("clicks",0))
        cpc = spend/clicks if clicks else 0
        criativos.append({
            "_rank": clicks,
            "_img_url": img_url,
            "img": "",
            "caption": caption,
            "cl": clicks,
            "cpc": round(cpc,2),
            "alcance": int(ins.get("reach",0)),
            "impressoes": int(ins.get("impressions",0)),
            "cpm": float(ins.get("cpm",0)),
            "frequencia": float(ins.get("frequency",0))
        })

    criativos.sort(key=lambda x: x["_rank"], reverse=True)
    top = criativos[:limite]

    log(f"Meta Ads: baixando thumbnails de {len(top)} criativos...")
    for i, cr in enumerate(top):
        url = cr.pop("_img_url","")
        cr.pop("_rank",None)
        if url:
            log(f"  [{i+1}/{len(top)}] {cr['caption'][:50]}…", "IMG")
            cr["img"] = img_b64(url, MAX_LOGO)

    log(f"Meta Ads: {len(top)} criativos com thumbnail prontos", "OK")
    return top

# ─────────────────────────────────────────────
# LER / ESCREVER DASHBOARD
# ─────────────────────────────────────────────

def js_to_json(js_text):
    """Converte JavaScript object literal para JSON válido."""
    import re as _re
    t = js_text

    # 1. Remover comentários de linha // ...
    t = _re.sub(r'//[^\n]*', '', t)

    # 2. Remover comentários de bloco /* ... */
    t = _re.sub(r'/\*.*?\*/', '', t, flags=_re.DOTALL)

    # 3. Converter aspas simples para duplas (com cuidado com apostrofos)
    #    Substitui strings 'texto' por "texto"
    def fix_single_quotes(m):
        inner = m.group(1)
        # Escapar aspas duplas existentes dentro da string
        inner = inner.replace('"', '\\"')
        # Remover escapes de aspas simples
        inner = inner.replace("\\'", "'")
        return f'"{inner}"'
    t = _re.sub(r"'((?:[^'\\]|\\.)*)'", fix_single_quotes, t)

    # 4. Adicionar aspas duplas às chaves sem aspas
    #    Ex: id: → "id":
    t = _re.sub(r'(?<!["\w])(\b[a-zA-Z_]\w*\b)\s*:', r'"\1":', t)

    # 5. Remover vírgulas finais antes de } ou ]
    t = _re.sub(r',(\s*[}\]])', r'\1', t)

    # 6. Remover chaves duplicadas (artefato do passo 4)
    t = _re.sub(r'"("[\w]+")":', r'\1:', t)

    return t

def ler_seed(dashboard_path):
    with open(dashboard_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Capturar o bloco SEED_DATA completo (pode ter colchetes aninhados)
    m = re.search(r'const SEED_DATA = (\[)', html)
    if not m:
        print("✗ SEED_DATA não encontrado no dashboard")
        sys.exit(1)

    # Encontrar o fechamento correto do array (balancear colchetes)
    start = m.start(1)
    depth = 0
    end = start
    for i, ch in enumerate(html[start:], start):
        if ch == '[': depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    seed_js = html[start:end]

    # Criar um objeto "match" compatível
    class FakeMatch:
        def __init__(self, s, e, g):
            self._s, self._e, self._g = s, e, g
        def start(self, n=0): return self._s
        def end(self, n=0): return self._e
        def group(self, n=0): return self._g

    fake_m = FakeMatch(start, end, seed_js)

    # Tentar json5 primeiro (mais robusto)
    try:
        import json5
        seed = json5.loads(seed_js)
        return html, seed, fake_m
    except ImportError:
        pass

    # Fallback: conversão manual JS → JSON
    try:
        seed_json = js_to_json(seed_js)
        seed = json.loads(seed_json)
        return html, seed, fake_m
    except json.JSONDecodeError as e:
        # Tentar instalar json5 automaticamente
        print("  → Instalando json5 para leitura de JavaScript...")
        os.system("pip install json5 -q")
        try:
            import json5
            seed = json5.loads(seed_js)
            return html, seed, fake_m
        except Exception as e2:
            print(f"✗ Erro ao parsear SEED_DATA: {e}")
            print(f"  Tente: pip install json5")
            sys.exit(1)

def salvar_seed(html, seed, match, dashboard_path):
    novo_seed = json.dumps(seed, ensure_ascii=False, indent=2)
    novo_html = html[:match.start(1)] + novo_seed + html[match.end(1):]
    with open(dashboard_path,"w",encoding="utf-8") as f:
        f.write(novo_html)
    kb = os.path.getsize(dashboard_path) / 1024
    log(f"Dashboard salvo: {dashboard_path} ({kb:.0f} KB)", "OK")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Busca imagens e injeta no dashboard")
    parser.add_argument("--periodo", help="ID do período (ex: marco_2026). Padrão: todos")
    parser.add_argument("--sem-ads", action="store_true", help="Pular criativos Meta Ads")
    parser.add_argument("--sem-fb", action="store_true", help="Pular posts do Facebook")
    args = parser.parse_args()

    # Carregar config
    if not os.path.exists(CONFIG_FILE):
        print(f"✗ {CONFIG_FILE} não encontrado")
        sys.exit(1)
    with open(CONFIG_FILE,"r",encoding="utf-8") as f:
        config = json.load(f)

    cliente = next((c for c in config.get("clientes",[]) if c.get("ativo",True)), None)
    if not cliente:
        print("✗ Nenhum cliente ativo no config")
        sys.exit(1)

    token = (cliente.get("ads",{}).get("access_token") or
             cliente.get("instagram",{}).get("access_token") or
             cliente.get("facebook",{}).get("access_token",""))

    if not token or "TODO" in token.upper():
        print("✗ Token não configurado no meta_config.json")
        print("  Preencha os campos access_token com o token real")
        sys.exit(1)

    ig_id = cliente.get("instagram",{}).get("instagram_business_id","")
    page_id = cliente.get("facebook",{}).get("page_id","")
    ad_acc = cliente.get("ads",{}).get("ad_account_id","")

    # Ler dashboard
    dashboard_path = DASHBOARD_FILE
    if not os.path.exists(dashboard_path):
        dashboard_path = os.path.join(os.path.dirname(__file__), DASHBOARD_FILE)

    html, seed, match = ler_seed(dashboard_path)
    total_periodos = len(seed)

    print(f"\n{'═'*55}")
    print(f"  fetch_imagens.py — {cliente['nome']}")
    print(f"  {total_periodos} períodos no dashboard")
    print(f"{'═'*55}")

    periodos_alvo = seed
    if args.periodo:
        periodos_alvo = [p for p in seed if p.get("id")==args.periodo]
        if not periodos_alvo:
            print(f"✗ Período '{args.periodo}' não encontrado")
            print(f"  IDs disponíveis: {[p['id'] for p in seed]}")
            sys.exit(1)

    imagens_total = 0

    for i, periodo in enumerate(periodos_alvo):
        inicio = periodo.get("inicio","")
        fim = periodo.get("fim","")
        nome = periodo.get("nome","?")

        print(f"\n  [{i+1}/{len(periodos_alvo)}] {nome} ({inicio} → {fim})")
        print(f"  {'─'*45}")

        # ── INSTAGRAM ──
        if ig_id:
            posts_ig = ig_top_posts(token, ig_id, inicio, fim, limite=10)
            if posts_ig:
                periodo["instagram"]["ig_top_posts"] = posts_ig
                imgs = sum(1 for p in posts_ig if p.get("img"))
                imagens_total += imgs
                log(f"Instagram: {imgs} imagens adicionadas", "OK")
        else:
            log("Instagram: ID não configurado — pulando", "WARN")

        # ── FACEBOOK ──
        if not args.sem_fb and page_id:
            posts_fb = fb_top_posts(token, page_id, inicio, fim, limite=10)
            if posts_fb:
                periodo["facebook"]["fb_top_posts"] = posts_fb
                imgs = sum(1 for p in posts_fb if p.get("img"))
                imagens_total += imgs
                log(f"Facebook: {imgs} imagens adicionadas", "OK")
        elif not page_id:
            log("Facebook: page_id não configurado — pulando", "WARN")

        # ── META ADS CRIATIVOS ──
        if not args.sem_ads and ad_acc:
            crs = meta_criativos(token, ad_acc, inicio, fim, limite=10)
            if crs:
                periodo["meta_ads"]["meta_criativos"] = crs
                imgs = sum(1 for c in crs if c.get("img"))
                imagens_total += imgs
                log(f"Meta Ads: {imgs} thumbnails adicionadas", "OK")

        # Salvar após cada período (não perder progresso)
        salvar_seed(html, seed, match, dashboard_path)
        # Re-ler HTML atualizado para próxima iteração
        html, seed, match = ler_seed(dashboard_path)

    print(f"\n{'='*55}")
    print(f"  ✓ Concluído! {imagens_total} imagens injetadas no dashboard")
    print(f"  Arquivo: {dashboard_path}")
    print(f"  Abra o dashboard no navegador para ver as imagens")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
