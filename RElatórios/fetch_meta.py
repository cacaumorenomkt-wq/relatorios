"""
fetch_meta.py — Coleta dados do Meta (Instagram + Facebook + Ads) para o Dashboard
Versão: 1.0

Uso:
    python fetch_meta.py                        → puxa os últimos 30 dias de todos os clientes
    python fetch_meta.py --cliente "Nome"       → apenas um cliente específico
    python fetch_meta.py --dias 60              → período customizado
    python fetch_meta.py --inicio 2026-03-01 --fim 2026-03-31  → datas exatas

Pré-requisitos:
    pip install requests pandas
"""

import json
import os
import sys
import argparse
import requests
import csv
from datetime import datetime, timedelta
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────────
GRAPH_API_VERSION = "v20.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
CONFIG_FILE = "meta_config.json"
OUTPUT_DIR = "dados_meta"

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def log(msg, level="INFO"):
    symbols = {"INFO": "→", "OK": "✓", "WARN": "⚠", "ERR": "✗"}
    print(f"{symbols.get(level, '·')} {msg}")

def api_get(url, params):
    """Faz uma chamada GET para a Graph API com tratamento de erros."""
    try:
        resp = requests.get(url, params=params, timeout=30)
        data = resp.json()
        if "error" in data:
            err = data["error"]
            log(f"Erro da API: {err.get('message', 'desconhecido')} (código {err.get('code')})", "ERR")
            return None
        return data
    except requests.exceptions.RequestException as e:
        log(f"Falha de conexão: {e}", "ERR")
        return None

def fmt_date(dt):
    return dt.strftime("%Y-%m-%d")

def br_date(dt_str):
    """Converte 2026-03-15 para 15/03/2026"""
    try:
        return datetime.strptime(dt_str, "%Y-%m-%d").strftime("%d/%m/%Y")
    except:
        return dt_str

# ─────────────────────────────────────────────
# INSTAGRAM — INSIGHTS ORGÂNICOS
# ─────────────────────────────────────────────
def fetch_instagram_organic(cliente, inicio, fim):
    """Puxa métricas diárias orgânicas do Instagram Business."""
    ig = cliente.get("instagram", {})
    ig_id = ig.get("instagram_business_id")
    token = ig.get("access_token")
    nome = cliente["nome"]

    if not ig_id or not token or "TOKEN" in token:
        log(f"[{nome}] Instagram não configurado — pulando", "WARN")
        return []

    log(f"[{nome}] Buscando Instagram orgânico ({inicio} → {fim})...")

    # Métricas de conta por dia
    metrics = "reach,impressions,profile_views,website_clicks,follower_count"
    url = f"{BASE_URL}/{ig_id}/insights"
    params = {
        "metric": metrics,
        "period": "day",
        "since": inicio,
        "until": fim,
        "access_token": token
    }
    data = api_get(url, params)

    rows = {}
    if data and "data" in data:
        for metric_data in data["data"]:
            metric_name = metric_data["name"]
            for value_entry in metric_data.get("values", []):
                date = value_entry.get("end_time", "")[:10]
                if date not in rows:
                    rows[date] = {
                        "data": br_date(date),
                        "campanha": "Orgânico Instagram",
                        "plataforma": "instagram",
                        "tipo": "organico",
                        "alcance": 0, "impressoes": 0, "cliques": 0,
                        "ctr": 0, "cpc": 0, "investimento": 0,
                        "curtidas": 0, "comentarios": 0, "compartilhamentos": 0,
                        "salvamentos": 0, "seguidores": 0, "conversoes": 0, "roas": 0,
                        "texto_post": ""
                    }
                field_map = {
                    "reach": "alcance",
                    "impressions": "impressoes",
                    "website_clicks": "cliques",
                    "follower_count": "seguidores"
                }
                if metric_name in field_map:
                    rows[date][field_map[metric_name]] = value_entry.get("value", 0)

    # Buscar posts individuais para engajamento
    posts_url = f"{BASE_URL}/{ig_id}/media"
    posts_params = {
        "fields": "id,timestamp,caption,like_count,comments_count,media_type",
        "since": inicio,
        "until": fim,
        "limit": 50,
        "access_token": token
    }
    posts_data = api_get(posts_url, posts_params)

    if posts_data and "data" in posts_data:
        for post in posts_data["data"]:
            date = post.get("timestamp", "")[:10]
            if date in rows:
                rows[date]["curtidas"] += post.get("like_count", 0)
                rows[date]["comentarios"] += post.get("comments_count", 0)
                if not rows[date]["texto_post"] and post.get("caption"):
                    rows[date]["texto_post"] = post["caption"][:200]

    result = list(rows.values())
    log(f"[{nome}] Instagram orgânico: {len(result)} dias coletados", "OK")
    return result

# ─────────────────────────────────────────────
# FACEBOOK — INSIGHTS ORGÂNICOS
# ─────────────────────────────────────────────
def fetch_facebook_organic(cliente, inicio, fim):
    """Puxa métricas diárias orgânicas da Página do Facebook."""
    fb = cliente.get("facebook", {})
    page_id = fb.get("page_id")
    token = fb.get("access_token")
    nome = cliente["nome"]

    if not page_id or not token or "TOKEN" in token:
        log(f"[{nome}] Facebook não configurado — pulando", "WARN")
        return []

    log(f"[{nome}] Buscando Facebook orgânico ({inicio} → {fim})...")

    metrics = "page_impressions,page_reach,page_post_engagements,page_fan_adds"
    url = f"{BASE_URL}/{page_id}/insights"
    params = {
        "metric": metrics,
        "period": "day",
        "since": inicio,
        "until": fim,
        "access_token": token
    }
    data = api_get(url, params)

    rows = {}
    if data and "data" in data:
        for metric_data in data["data"]:
            metric_name = metric_data["name"]
            for value_entry in metric_data.get("values", []):
                date = value_entry.get("end_time", "")[:10]
                if date not in rows:
                    rows[date] = {
                        "data": br_date(date),
                        "campanha": "Orgânico Facebook",
                        "plataforma": "facebook",
                        "tipo": "organico",
                        "alcance": 0, "impressoes": 0, "cliques": 0,
                        "ctr": 0, "cpc": 0, "investimento": 0,
                        "curtidas": 0, "comentarios": 0, "compartilhamentos": 0,
                        "salvamentos": 0, "seguidores": 0, "conversoes": 0, "roas": 0,
                        "texto_post": ""
                    }
                field_map = {
                    "page_reach": "alcance",
                    "page_impressions": "impressoes",
                    "page_post_engagements": "curtidas",
                    "page_fan_adds": "seguidores"
                }
                if metric_name in field_map:
                    rows[date][field_map[metric_name]] = value_entry.get("value", 0)

    result = list(rows.values())
    log(f"[{nome}] Facebook orgânico: {len(result)} dias coletados", "OK")
    return result

# ─────────────────────────────────────────────
# META ADS — TRÁFEGO PAGO
# ─────────────────────────────────────────────
def fetch_meta_ads(cliente, inicio, fim):
    """Puxa dados de campanhas do Meta Ads Manager."""
    ads = cliente.get("ads", {})
    ad_account = ads.get("ad_account_id")
    token = ads.get("access_token")
    nome = cliente["nome"]

    if not ad_account or not token or "TOKEN" in token:
        log(f"[{nome}] Meta Ads não configurado — pulando", "WARN")
        return []

    log(f"[{nome}] Buscando Meta Ads ({inicio} → {fim})...")

    url = f"{BASE_URL}/{ad_account}/insights"
    fields = "campaign_name,date_start,impressions,reach,clicks,ctr,cpc,spend,actions,action_values,platform_position"
    params = {
        "fields": fields,
        "time_range": json.dumps({"since": inicio, "until": fim}),
        "time_increment": 1,
        "level": "campaign",
        "breakdowns": "publisher_platform",
        "access_token": token,
        "limit": 500
    }
    data = api_get(url, params)

    rows = []
    if data and "data" in data:
        for item in data["data"]:
            # Extrair conversões e receita das actions
            conversoes = 0
            receita = 0.0
            for action in item.get("actions", []):
                if action.get("action_type") in ["purchase", "lead", "complete_registration"]:
                    conversoes += int(action.get("value", 0))
            for action in item.get("action_values", []):
                if action.get("action_type") == "purchase":
                    receita += float(action.get("value", 0))

            spend = float(item.get("spend", 0))
            roas = (receita / spend) if spend > 0 else 0

            plataforma = item.get("publisher_platform", "meta").lower()
            if plataforma not in ["instagram", "facebook", "audience_network", "messenger"]:
                plataforma = "meta"

            rows.append({
                "data": br_date(item.get("date_start", "")),
                "campanha": item.get("campaign_name", "Sem nome"),
                "plataforma": plataforma,
                "tipo": "pago",
                "alcance": int(item.get("reach", 0)),
                "impressoes": int(item.get("impressions", 0)),
                "cliques": int(item.get("clicks", 0)),
                "ctr": float(item.get("ctr", 0)),
                "cpc": float(item.get("cpc", 0)),
                "investimento": spend,
                "curtidas": 0,
                "comentarios": 0,
                "compartilhamentos": 0,
                "salvamentos": 0,
                "seguidores": 0,
                "conversoes": conversoes,
                "roas": round(roas, 2),
                "texto_post": ""
            })

    # Paginação
    while data and "paging" in data and "next" in data["paging"]:
        data = api_get(data["paging"]["next"], {})
        if data and "data" in data:
            for item in data["data"]:
                spend = float(item.get("spend", 0))
                rows.append({
                    "data": br_date(item.get("date_start", "")),
                    "campanha": item.get("campaign_name", "Sem nome"),
                    "plataforma": item.get("publisher_platform", "meta").lower(),
                    "tipo": "pago",
                    "alcance": int(item.get("reach", 0)),
                    "impressoes": int(item.get("impressions", 0)),
                    "cliques": int(item.get("clicks", 0)),
                    "ctr": float(item.get("ctr", 0)),
                    "cpc": float(item.get("cpc", 0)),
                    "investimento": spend,
                    "curtidas": 0, "comentarios": 0, "compartilhamentos": 0,
                    "salvamentos": 0, "seguidores": 0, "conversoes": 0, "roas": 0,
                    "texto_post": ""
                })

    log(f"[{nome}] Meta Ads: {len(rows)} registros coletados", "OK")
    return rows

# ─────────────────────────────────────────────
# EXPORTAR CSV
# ─────────────────────────────────────────────
def export_csv(rows, filepath):
    """Salva os dados em CSV compatível com o dashboard."""
    if not rows:
        log("Nenhum dado para exportar", "WARN")
        return

    fields = ["data", "campanha", "plataforma", "tipo", "alcance", "impressoes",
              "cliques", "ctr", "cpc", "investimento", "curtidas", "comentarios",
              "compartilhamentos", "salvamentos", "seguidores", "conversoes", "roas", "texto_post"]

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, 0) for k in fields})

    log(f"CSV exportado: {filepath} ({len(rows)} linhas)", "OK")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Coleta dados do Meta para o Dashboard")
    parser.add_argument("--cliente", help="Nome do cliente específico")
    parser.add_argument("--dias", type=int, default=30, help="Últimos N dias (padrão: 30)")
    parser.add_argument("--inicio", help="Data de início (YYYY-MM-DD)")
    parser.add_argument("--fim", help="Data de fim (YYYY-MM-DD)")
    args = parser.parse_args()

    # Calcular período
    hoje = datetime.now()
    if args.inicio and args.fim:
        inicio = args.inicio
        fim = args.fim
    else:
        fim = fmt_date(hoje)
        inicio = fmt_date(hoje - timedelta(days=args.dias))

    log(f"Período: {inicio} → {fim}")

    # Carregar config
    if not os.path.exists(CONFIG_FILE):
        log(f"Arquivo {CONFIG_FILE} não encontrado. Crie ele com base no template.", "ERR")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    clientes = config.get("clientes", [])
    if args.cliente:
        clientes = [c for c in clientes if c["nome"].lower() == args.cliente.lower()]
        if not clientes:
            log(f"Cliente '{args.cliente}' não encontrado no config", "ERR")
            sys.exit(1)

    clientes_ativos = [c for c in clientes if c.get("ativo", True)]
    log(f"Processando {len(clientes_ativos)} cliente(s)...")

    # Criar pasta de saída
    Path(OUTPUT_DIR).mkdir(exist_ok=True)

    # Processar cada cliente
    for cliente in clientes_ativos:
        nome = cliente["nome"]
        log(f"\n{'─'*40}")
        log(f"Cliente: {nome}")
        log(f"{'─'*40}")

        all_rows = []
        all_rows.extend(fetch_instagram_organic(cliente, inicio, fim))
        all_rows.extend(fetch_facebook_organic(cliente, inicio, fim))
        all_rows.extend(fetch_meta_ads(cliente, inicio, fim))

        if all_rows:
            # Nome do arquivo: cliente_YYYY-MM-DD.csv
            safe_name = nome.replace(" ", "_").lower()
            filename = f"{OUTPUT_DIR}/{safe_name}_{inicio}_a_{fim}.csv"
            export_csv(all_rows, filename)
            log(f"[{nome}] Total: {len(all_rows)} registros → {filename}", "OK")
        else:
            log(f"[{nome}] Nenhum dado coletado. Verifique o config.json", "WARN")

    print(f"\n{'='*40}")
    print("✓ Coleta finalizada!")
    print(f"  Arquivos salvos em: ./{OUTPUT_DIR}/")
    print(f"  Abra o dashboard e faça upload do CSV gerado.")
    print(f"{'='*40}")

if __name__ == "__main__":
    main()
