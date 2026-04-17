"""
update_dashboard.py — Atualização automática do dashboard semanal
Versão: 2.0

O que faz toda segunda-feira:
  1. Puxa Meta Ads (campanhas, cliques, gasto, CPC, CPM, alcance) via API
  2. Puxa Instagram orgânico (seguidores, alcance, engajamento) via API
  3. Puxa top 10 posts do Instagram COM IMAGEM via API (media_url)
  4. Puxa Facebook Página (seguidores, alcance, engajamentos) via API
  5. Puxa top 10 posts do Facebook COM IMAGEM via API
  6. Puxa criativos do Meta Ads COM IMAGEM via API
  7. Injeta tudo no dashboard-campanhas.html como novo período
  8. Faz push para o GitHub (publica online)

Uso:
    python update_dashboard.py                   # semana atual (últimos 7 dias)
    python update_dashboard.py --dias 30         # últimos 30 dias
    python update_dashboard.py --inicio 2026-04-01 --fim 2026-04-07

Pré-requisito:
    Preencher meta_config.json com os dados reais da Banda Universos
    pip install requests Pillow
"""

import json
import sys
import re
import argparse
import requests
import base64
import os
from datetime import datetime, timedelta
from pathlib import Path
from io import BytesIO

GRAPH_API_VERSION = "v20.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
CONFIG_FILE = "meta_config.json"
DASHBOARD_FILE = "dashboard-campanhas.html"

COLORS = ['#7C3AED','#A855F7','#C084FC','#6366F1','#2563EB','#E1306C','#059669','#D97706']

# ─────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────

def log(msg, level="INFO"):
    symbols = {"INFO": "→", "OK": "✓", "WARN": "⚠", "ERR": "✗"}
    print(f"  {symbols.get(level,'·')} {msg}")

def api_get(url, params=None):
    try:
        resp = requests.get(url, params=params or {}, timeout=30)
        data = resp.json()
        if "error" in data:
            err = data["error"]
            log(f"API erro: {err.get('message','?')} (cod {err.get('code')})", "ERR")
            return None
        return data
    except Exception as e:
        log(f"Conexão falhou: {e}", "ERR")
        return None

def download_image_b64(url, max_size=600):
    """Baixa uma imagem de URL, redimensiona e retorna base64."""
    if not url:
        return ""
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return ""

        # Tentar usar Pillow para redimensionar
        try:
            from PIL import Image
            img = Image.open(BytesIO(resp.content))
            img.thumbnail((max_size, max_size), Image.LANCZOS)
            buf = BytesIO()
            fmt = "JPEG" if img.mode != "RGBA" else "PNG"
            img.convert("RGB").save(buf, format="JPEG", quality=70)
            b64 = base64.b64encode(buf.getvalue()).decode()
            return f"data:image/jpeg;base64,{b64}"
        except ImportError:
            # Sem Pillow: usar imagem original
            b64 = base64.b64encode(resp.content).decode()
            ct = resp.headers.get("content-type", "image/jpeg")
            return f"data:{ct};base64,{b64}"
    except Exception as e:
        log(f"Falha ao baixar imagem {url[:60]}...: {e}", "WARN")
        return ""

def fmt_ymd(dt):
    return dt.strftime("%Y-%m-%d")

def semana_label(inicio, fim):
    d1 = datetime.strptime(inicio, "%Y-%m-%d")
    d2 = datetime.strptime(fim, "%Y-%m-%d")
    dias = (d2 - d1).days + 1
    if dias <= 10:
        return f"Semana {d1.strftime('%d/%m')}–{d2.strftime('%d/%m/%Y')}"
    elif dias <= 20:
        return f"Quinzena {d1.strftime('%d/%m')}–{d2.strftime('%d/%m/%Y')}"
    else:
        return f"{d1.strftime('%B %Y').capitalize()}"

# ─────────────────────────────────────────────
# META ADS
# ─────────────────────────────────────────────

def fetch_meta_ads(token, ad_account_id, inicio, fim):
    """Puxa campanhas + criativos do Meta Ads."""
    log("Meta Ads: campanhas...")
    url = f"{BASE_URL}/{ad_account_id}/insights"
    params = {
        "fields": "campaign_name,campaign_id,impressions,reach,clicks,ctr,cpc,cpm,spend",
        "time_range": json.dumps({"since": inicio, "until": fim}),
        "level": "campaign",
        "access_token": token,
        "limit": 100
    }
    data = api_get(url, params)
    if not data or "data" not in data:
        log("Meta Ads: sem dados", "WARN")
        return {"gasto": 0, "campanhas": [], "meta_criativos": []}

    campanhas = []
    gasto_total = 0.0
    for i, item in enumerate(data["data"]):
        gasto = float(item.get("spend", 0))
        gasto_total += gasto
        campanhas.append({
            "id": f"c{i+1}",
            "nome": item.get("campaign_name", f"Campanha {i+1}"),
            "campaign_id": item.get("campaign_id", ""),
            "cliques": int(item.get("clicks", 0)),
            "alcance": int(item.get("reach", 0)),
            "impressoes": int(item.get("impressions", 0)),
            "cpm": float(item.get("cpm", 0)),
            "gasto": round(gasto, 2),
            "cor": COLORS[i % len(COLORS)],
            # FB/IG split: buscar depois com breakdowns
            "fb_cl": 0, "ig_cl": 0,
            "fb_alc": 0, "ig_alc": 0,
            "fb_g": 0, "ig_g": 0
        })

    log(f"Meta Ads: {len(campanhas)} campanhas, R$ {gasto_total:.2f} total", "OK")

    # Split por plataforma (breakdowns)
    params_split = {**params}
    params_split["breakdowns"] = "publisher_platform"
    params_split["level"] = "campaign"
    split_data = api_get(url, params_split)
    if split_data and "data" in split_data:
        for item in split_data["data"]:
            camp_id = item.get("campaign_id")
            plat = item.get("publisher_platform", "").lower()
            camp = next((c for c in campanhas if c["campaign_id"] == camp_id), None)
            if camp:
                cl = int(item.get("clicks", 0))
                alc = int(item.get("reach", 0))
                g = float(item.get("spend", 0))
                if plat == "facebook":
                    camp["fb_cl"] = cl; camp["fb_alc"] = alc; camp["fb_g"] = round(g, 2)
                elif plat == "instagram":
                    camp["ig_cl"] = cl; camp["ig_alc"] = alc; camp["ig_g"] = round(g, 2)

    # Criativos principais (top 5 por cliques)
    log("Meta Ads: criativos...")
    criativos = fetch_meta_criativos(token, ad_account_id, inicio, fim)

    return {
        "gasto": round(gasto_total, 2),
        "campanhas": campanhas,
        "meta_criativos": criativos
    }

def fetch_meta_criativos(token, ad_account_id, inicio, fim):
    """Puxa top criativos com imagem thumbnail."""
    url = f"{BASE_URL}/{ad_account_id}/ads"
    params = {
        "fields": "name,creative{thumbnail_url,image_url,body,title},insights.date_preset(last_7d){clicks,reach,impressions,cpc,cpm,spend,frequency}",
        "limit": 20,
        "access_token": token
    }
    data = api_get(url, params)
    criativos = []
    if not data or "data" not in data:
        return criativos

    for ad in data["data"][:10]:
        creative = ad.get("creative", {})
        insights_list = ad.get("insights", {}).get("data", [{}])
        ins = insights_list[0] if insights_list else {}

        # Obter imagem do criativo
        img_url = creative.get("thumbnail_url") or creative.get("image_url") or ""
        img_b64 = download_image_b64(img_url) if img_url else ""

        caption = creative.get("body") or creative.get("title") or ad.get("name", "Criativo")
        if len(caption) > 120:
            caption = caption[:117] + "…"

        cpc = float(ins.get("cpc", 0))
        spend = float(ins.get("spend", 0))
        if cpc == 0 and ins.get("clicks") and spend:
            cpc = spend / int(ins["clicks"])

        criativos.append({
            "img": img_b64,
            "caption": caption,
            "cl": int(ins.get("clicks", 0)),
            "cpc": round(cpc, 2),
            "alcance": int(ins.get("reach", 0)),
            "impressoes": int(ins.get("impressions", 0)),
            "cpm": float(ins.get("cpm", 0)),
            "frequencia": float(ins.get("frequency", 0))
        })

    # Ordenar por cliques
    criativos.sort(key=lambda x: x["cl"], reverse=True)
    log(f"Meta Ads: {len(criativos)} criativos com imagem", "OK")
    return criativos[:10]

# ─────────────────────────────────────────────
# INSTAGRAM ORGÂNICO
# ─────────────────────────────────────────────

def fetch_instagram(token, ig_business_id, inicio, fim):
    """Puxa métricas orgânicas + top 10 posts com imagem."""
    log("Instagram: métricas orgânicas...")

    # 1. Conta de seguidores
    profile = api_get(f"{BASE_URL}/{ig_business_id}", {
        "fields": "followers_count,media_count",
        "access_token": token
    })
    seguidores = 0
    if profile:
        seguidores = int(profile.get("followers_count", 0))
        log(f"Instagram: {seguidores:,} seguidores", "OK")

    # 2. Insights de conta (alcance, impressões)
    insights_url = f"{BASE_URL}/{ig_business_id}/insights"
    ins_data = api_get(insights_url, {
        "metric": "reach,impressions,follower_count,profile_views",
        "period": "day",
        "since": inicio,
        "until": fim,
        "access_token": token
    })

    alcance = 0
    impressoes = 0
    seg_novos = 0

    if ins_data and "data" in ins_data:
        for m in ins_data["data"]:
            total = sum(v.get("value", 0) for v in m.get("values", []))
            if m["name"] == "reach":
                alcance = total
            elif m["name"] == "impressions":
                impressoes = total
            elif m["name"] == "follower_count":
                seg_novos = total  # variação no período

    # 3. Top posts com imagem e métricas individuais
    log("Instagram: top posts (com imagens)...")
    posts_data = api_get(f"{BASE_URL}/{ig_business_id}/media", {
        "fields": "id,timestamp,caption,like_count,comments_count,media_type,media_url,thumbnail_url,permalink",
        "since": inicio,
        "until": fim,
        "limit": 50,
        "access_token": token
    })

    posts_raw = []
    if posts_data and "data" in posts_data:
        for p in posts_data["data"]:
            # Buscar insights do post (reach, impressions, saved, shares)
            p_ins = api_get(f"{BASE_URL}/{p['id']}/insights", {
                "metric": "reach,impressions,saved,shares",
                "access_token": token
            })
            p_reach = p_imp = p_saved = p_shares = 0
            if p_ins and "data" in p_ins:
                for m in p_ins["data"]:
                    v = m.get("values", [{}])[0].get("value", 0) if m.get("values") else 0
                    if m["name"] == "reach": p_reach = v
                    elif m["name"] == "impressions": p_imp = v
                    elif m["name"] == "saved": p_saved = v
                    elif m["name"] == "shares": p_shares = v

            curtidas = int(p.get("like_count", 0))
            comentarios = int(p.get("comments_count", 0))
            tipo = p.get("media_type", "IMAGE")
            tipo_label = "Reels" if tipo == "VIDEO" else "Carrossel" if tipo == "CAROUSEL_ALBUM" else "Feed"

            # Baixar imagem (thumbnail para vídeo, media_url para foto)
            img_url = p.get("thumbnail_url") or p.get("media_url", "")

            posts_raw.append({
                "id": p["id"],
                "alcance": p_reach,
                "curtidas": curtidas,
                "comentarios": comentarios,
                "salvamentos": p_saved,
                "compartilhamentos": p_shares,
                "impressoes": p_imp,
                "tipo": tipo_label,
                "caption": (p.get("caption") or "")[:120],
                "img_url": img_url
            })

    # Ordenar por alcance (maior primeiro)
    posts_raw.sort(key=lambda x: x["alcance"], reverse=True)
    top10 = posts_raw[:10]

    # Baixar imagens dos top 10
    log(f"Instagram: baixando imagens de {len(top10)} posts...")
    ig_top_posts = []
    for post in top10:
        img_b64 = download_image_b64(post["img_url"])
        ig_top_posts.append({
            "img": img_b64,
            "caption": post["caption"],
            "alcance": post["alcance"],
            "curtidas": post["curtidas"],
            "comentarios": post["comentarios"],
            "salvamentos": post["salvamentos"],
            "compartilhamentos": post["compartilhamentos"],
            "tipo": post["tipo"]
        })

    # Calcular totais de engajamento
    curtidas_total = sum(p["curtidas"] for p in posts_raw)
    comentarios_total = sum(p["comentarios"] for p in posts_raw)
    compartilhamentos_total = sum(p["compartilhamentos"] for p in posts_raw)
    salvamentos_total = sum(p["salvamentos"] for p in posts_raw)

    # Contadores por tipo
    reels_count = sum(1 for p in posts_raw if p["tipo"] == "Reels")
    stories_count = 0  # Stories não aparecem no /media endpoint
    posts_count = len(posts_raw)

    # Reels views
    reels_views = sum(p.get("impressoes", 0) for p in posts_raw if p["tipo"] == "Reels")

    # Taxa de engajamento = (curtidas + comentários) / alcance * 100
    eng_pct = 0
    if alcance > 0:
        eng_pct = round((curtidas_total + comentarios_total) / alcance * 100, 2)

    log(f"Instagram: alcance {alcance:,}, engajamento {eng_pct}%, {posts_count} posts", "OK")

    return {
        "seguidores": seguidores,
        "seg_novos": max(0, seg_novos),
        "alcance": alcance,
        "impressoes": impressoes,
        "engajamento_pct": eng_pct,
        "posts": posts_count,
        "reels": reels_count,
        "stories": stories_count,
        "curtidas": curtidas_total,
        "comentarios": comentarios_total,
        "compartilhamentos": compartilhamentos_total,
        "salvamentos": salvamentos_total,
        "reels_views": reels_views,
        "stories_views": 0,  # Stories Insights requerem permissão extra
        "ig_top_posts": ig_top_posts
    }

# ─────────────────────────────────────────────
# FACEBOOK PÁGINA
# ─────────────────────────────────────────────

def fetch_facebook(token, page_id, inicio, fim):
    """Puxa métricas orgânicas + top 10 posts da página."""
    log("Facebook: métricas da página...")

    # Seguidores da página
    page_data = api_get(f"{BASE_URL}/{page_id}", {
        "fields": "fan_count,followers_count,name",
        "access_token": token
    })
    seguidores = 0
    if page_data:
        seguidores = int(page_data.get("fan_count") or page_data.get("followers_count", 0))
        log(f"Facebook: {seguidores:,} seguidores da página", "OK")

    # Insights da página
    ins_data = api_get(f"{BASE_URL}/{page_id}/insights", {
        "metric": "page_reach,page_impressions,page_post_engagements,page_fan_adds",
        "period": "day",
        "since": inicio,
        "until": fim,
        "access_token": token
    })

    alcance = impressoes = reacoes = seg_novos = 0
    if ins_data and "data" in ins_data:
        for m in ins_data["data"]:
            total = sum(v.get("value", 0) for v in m.get("values", []))
            if m["name"] == "page_reach": alcance = total
            elif m["name"] == "page_impressions": impressoes = total
            elif m["name"] == "page_post_engagements": reacoes = total
            elif m["name"] == "page_fan_adds": seg_novos = total

    # Top posts com imagem
    log("Facebook: top posts (com imagens)...")
    posts_data = api_get(f"{BASE_URL}/{page_id}/posts", {
        "fields": "id,message,created_time,attachments{media{image{src}},type},insights.metric(post_impressions,post_reach,post_engaged_users,post_clicks){values}",
        "since": inicio,
        "until": fim,
        "limit": 30,
        "access_token": token
    })

    fb_posts_raw = []
    if posts_data and "data" in posts_data:
        for p in posts_data["data"]:
            p_reach = p_imp = p_cliques = 0
            insights = p.get("insights", {}).get("data", [])
            for m in insights:
                v = m.get("values", [{}])[0].get("value", 0)
                if m["name"] == "post_reach": p_reach = v
                elif m["name"] == "post_impressions": p_imp = v
                elif m["name"] == "post_clicks": p_cliques = v

            # Imagem do post
            img_url = ""
            attachments = p.get("attachments", {}).get("data", [{}])
            if attachments:
                att = attachments[0]
                media = att.get("media", {})
                img_url = media.get("image", {}).get("src", "")

            att_type = attachments[0].get("type", "photo") if attachments else "photo"
            tipo_label = "Reels" if att_type in ("video_autoplay", "video_share") else "Carrossel" if att_type == "album" else "Feed"

            msg = (p.get("message") or "")[:120]
            fb_posts_raw.append({
                "alcance": p_reach,
                "visualizacoes": p_imp,
                "cliques": p_cliques,
                "tipo": tipo_label,
                "caption": msg,
                "img_url": img_url
            })

    # Ordenar por alcance
    fb_posts_raw.sort(key=lambda x: x["alcance"], reverse=True)
    top10 = fb_posts_raw[:10]

    log(f"Facebook: baixando imagens de {len(top10)} posts...")
    fb_top_posts = []
    for post in top10:
        img_b64 = download_image_b64(post["img_url"])
        fb_top_posts.append({
            "img": img_b64,
            "caption": post["caption"],
            "alcance": post["alcance"],
            "visualizacoes": post["visualizacoes"],
            "cliques": post["cliques"],
            "tipo": post["tipo"]
        })

    log(f"Facebook: alcance {alcance:,}, engajamentos {reacoes:,}", "OK")

    return {
        "seguidores": seguidores,
        "seg_novos": seg_novos,
        "alcance": alcance,
        "impressoes": impressoes,
        "posts": len(fb_posts_raw),
        "videos": 0,
        "reacoes": reacoes,
        "comentarios": 0,
        "compartilhamentos": 0,
        "cliques_link": 0,
        "videos_views": 0,
        "engajamento_pct": 0,
        "fb_top_posts": fb_top_posts
    }

# ─────────────────────────────────────────────
# GERAR PERÍODO
# ─────────────────────────────────────────────

def gerar_periodo(cliente, inicio, fim):
    """Monta o objeto de período completo para injeção no dashboard."""
    nome_cliente = cliente["nome"]
    token = (
        cliente.get("ads", {}).get("access_token") or
        cliente.get("instagram", {}).get("access_token") or
        cliente.get("facebook", {}).get("access_token")
    )

    periodo_id = f"auto_{inicio.replace('-','')}"
    nome_label = semana_label(inicio, fim)

    print(f"\n{'═'*50}")
    print(f"  Coletando: {nome_cliente}")
    print(f"  Período:   {inicio} → {fim}")
    print(f"{'═'*50}")

    # Meta Ads
    meta_ads = {"gasto": 0, "campanhas": [], "meta_criativos": []}
    ads_cfg = cliente.get("ads", {})
    if ads_cfg.get("ad_account_id") and token and "TOKEN" not in token.upper():
        meta_ads = fetch_meta_ads(token, ads_cfg["ad_account_id"], inicio, fim)
    else:
        log("Meta Ads: token não configurado — usando dados vazios", "WARN")

    # Instagram
    instagram = {"seguidores": 0, "seg_novos": 0, "alcance": 0, "impressoes": 0,
                 "engajamento_pct": 0, "posts": 0, "reels": 0, "stories": 0,
                 "curtidas": 0, "comentarios": 0, "compartilhamentos": 0,
                 "salvamentos": 0, "reels_views": 0, "stories_views": 0, "ig_top_posts": []}
    ig_cfg = cliente.get("instagram", {})
    if ig_cfg.get("instagram_business_id") and token and "TOKEN" not in token.upper():
        instagram = fetch_instagram(token, ig_cfg["instagram_business_id"], inicio, fim)
    else:
        log("Instagram: não configurado — usando dados vazios", "WARN")

    # Facebook
    facebook = {"seguidores": 0, "seg_novos": 0, "alcance": 0, "impressoes": 0,
                "posts": 0, "videos": 0, "reacoes": 0, "comentarios": 0,
                "compartilhamentos": 0, "cliques_link": 0, "videos_views": 0,
                "engajamento_pct": 0, "fb_top_posts": []}
    fb_cfg = cliente.get("facebook", {})
    if fb_cfg.get("page_id") and token and "TOKEN" not in token.upper():
        facebook = fetch_facebook(token, fb_cfg["page_id"], inicio, fim)
    else:
        log("Facebook: não configurado — usando dados vazios", "WARN")

    periodo = {
        "id": periodo_id,
        "nome": nome_label,
        "inicio": inicio,
        "fim": fim,
        "meta_ads": meta_ads,
        "instagram": instagram,
        "facebook": facebook,
        "analise": (
            f"Período {inicio} a {fim}. "
            f"Meta Ads: R$ {meta_ads['gasto']:.2f} investidos, "
            f"{sum(c['cliques'] for c in meta_ads['campanhas'])} cliques. "
            f"Instagram: {instagram['seguidores']:,} seguidores, "
            f"engajamento {instagram['engajamento_pct']}%."
        ),
        "recomendacoes": [
            {"icon": "📊", "txt": f"<strong>Análise automática do período {inicio} a {fim}:</strong> Revise os dados acima e adicione suas recomendações editando este período."}
        ]
    }
    return periodo

# ─────────────────────────────────────────────
# INJETAR NO DASHBOARD
# ─────────────────────────────────────────────

def injetar_no_dashboard(periodo, dashboard_path):
    """
    Injeta o novo período no início do SEED_DATA no HTML do dashboard.
    Se já existir um período com o mesmo id, substitui.
    """
    if not os.path.exists(dashboard_path):
        log(f"Dashboard não encontrado: {dashboard_path}", "ERR")
        return False

    with open(dashboard_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Extrair SEED_DATA atual
    match = re.search(r'const SEED_DATA = (\[.*?\]);', html, re.DOTALL)
    if not match:
        log("SEED_DATA não encontrado no HTML", "ERR")
        return False

    try:
        seed_atual = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        log(f"Erro ao parsear SEED_DATA: {e}", "ERR")
        return False

    # Remover período com mesmo id se existir, adicionar no início
    seed_atual = [p for p in seed_atual if p.get("id") != periodo["id"]]
    seed_atual.insert(0, periodo)

    # Manter no máximo 12 períodos para não sobrecarregar o arquivo
    seed_atual = seed_atual[:12]

    # Serializar de volta (separadores compactos)
    novo_seed = json.dumps(seed_atual, ensure_ascii=False, indent=2)

    # Substituir no HTML
    novo_html = html[:match.start(1)] + novo_seed + html[match.end(1):]

    with open(dashboard_path, "w", encoding="utf-8") as f:
        f.write(novo_html)

    log(f"Dashboard atualizado: {len(seed_atual)} períodos no SEED_DATA", "OK")
    return True

# ─────────────────────────────────────────────
# PUSH GITHUB (opcional)
# ─────────────────────────────────────────────

def push_github(dashboard_path, inicio, fim, github_config=None):
    """Publica o dashboard atualizado no GitHub via API."""
    if not github_config:
        log("GitHub não configurado — pulando push", "WARN")
        return

    token = github_config.get("token")
    owner = github_config.get("owner")
    repo = github_config.get("repo")
    filename = os.path.basename(dashboard_path)

    if not all([token, owner, repo]):
        log("GitHub: configuração incompleta", "WARN")
        return

    log(f"GitHub: publicando {filename}...")

    # Obter SHA atual do arquivo
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{filename}"
    headers = {"Authorization": f"token {token}", "Content-Type": "application/json"}

    existing = requests.get(api_url, headers=headers)
    sha = existing.json().get("sha", "") if existing.status_code == 200 else ""

    # Ler e codificar arquivo
    with open(dashboard_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "message": f"Dashboard atualizado automaticamente — {inicio} a {fim}",
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha

    resp = requests.put(api_url, headers=headers, data=json.dumps(payload))
    if resp.status_code in (200, 201):
        log(f"GitHub: publicado com sucesso! {owner}/{repo}/{filename}", "OK")
    else:
        log(f"GitHub: erro {resp.status_code} — {resp.text[:100]}", "ERR")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Atualiza o dashboard de marketing automaticamente")
    parser.add_argument("--cliente", help="Nome exato do cliente no config (padrão: primeiro ativo)")
    parser.add_argument("--dias", type=int, default=7, help="Últimos N dias (padrão: 7)")
    parser.add_argument("--inicio", help="Data início YYYY-MM-DD")
    parser.add_argument("--fim", help="Data fim YYYY-MM-DD")
    parser.add_argument("--sem-github", action="store_true", help="Não publicar no GitHub")
    args = parser.parse_args()

    hoje = datetime.now()
    if args.inicio and args.fim:
        inicio = args.inicio
        fim = args.fim
    else:
        fim = fmt_ymd(hoje)
        inicio = fmt_ymd(hoje - timedelta(days=args.dias - 1))

    print(f"\n{'═'*50}")
    print(f"  update_dashboard.py — Atualização Automática")
    print(f"  Período: {inicio} → {fim}")
    print(f"{'═'*50}")

    # Carregar config
    if not os.path.exists(CONFIG_FILE):
        print(f"\n✗ Arquivo {CONFIG_FILE} não encontrado!")
        print(f"\n  Para configurar a Banda Universos, edite {CONFIG_FILE} com:")
        print(f"  - instagram_business_id: ID da conta Instagram Business")
        print(f"  - facebook.page_id: ID da página do Facebook")
        print(f"  - ads.ad_account_id: act_XXXXXXXXX do Meta Ads")
        print(f"  - access_token: token de acesso de longa duração")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    clientes = config.get("clientes", [])
    if args.cliente:
        clientes = [c for c in clientes if c["nome"].lower() == args.cliente.lower()]
    clientes_ativos = [c for c in clientes if c.get("ativo", True)]

    if not clientes_ativos:
        print("✗ Nenhum cliente ativo no config")
        sys.exit(1)

    dashboard_path = DASHBOARD_FILE
    if not os.path.exists(dashboard_path):
        # Tentar na pasta do script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        dashboard_path = os.path.join(script_dir, DASHBOARD_FILE)

    # Processar cada cliente ativo
    for cliente in clientes_ativos:
        try:
            periodo = gerar_periodo(cliente, inicio, fim)

            # Injetar no dashboard
            ok = injetar_no_dashboard(periodo, dashboard_path)

            # Push GitHub
            if ok and not args.sem_github:
                gh_cfg = config.get("github")
                push_github(dashboard_path, inicio, fim, gh_cfg)

            print(f"\n✓ {cliente['nome']} — dashboard atualizado com sucesso!")

        except Exception as e:
            print(f"\n✗ Erro ao processar {cliente['nome']}: {e}")
            import traceback; traceback.print_exc()

    print(f"\n{'='*50}")
    print(f"  Atualização concluída!")
    print(f"  Dashboard: {dashboard_path}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
