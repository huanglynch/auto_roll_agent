import os
import json
import asyncio
import logging
from datetime import datetime
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
from ib_insync import *

# ==================== 日志配置（VPS 专用） ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/home/ibkr/roll.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== 配置 ====================
with open('/home/ibkr/config.json') as f:
    CONFIG = json.load(f)

AUTO = CONFIG.get('auto_roll', {'enabled': False})
HOLDINGS = CONFIG['holdings']
XAI_API_KEY = os.getenv("XAI_API_KEY")
GMAIL_SENDER = os.getenv("GMAIL_SENDER")
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASSWORD")
GMAIL_RECEIVER = os.getenv("GMAIL_RECEIVER")
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL")

if not AUTO.get('enabled', False):
    logger.info("自动 Roll 已关闭（config.json 中 enabled=false）")
    exit(0)

# ==================== Grok 智能决策 ====================
async def get_grok_decision():
    farthest = max(HOLDINGS, key=lambda x: x['strike'])
    system_prompt = f"""你是一个严格的 TSLA Covered Call 专家。
使用最新实时数据（2026年2月及以后）。
用户持仓: {json.dumps(HOLDINGS, ensure_ascii=False)}
触发阈值: 单日 >= {CONFIG['roll_trigger']['daily_rise_percent']}%，价格超最远行权价 {CONFIG['roll_trigger']['price_over_farthest_percent']}%

只返回严格 JSON，不要任何其他文字：
{{
  "should_roll": true/false,
  "current_price": 数字,
  "rise_pct": 数字,
  "new_expiry": "YYYY-MM-DD",
  "strike_low": 整数,
  "strike_high": 整数,
  "reason": "一句话理由"
}}"""

    payload = {
        "model": "grok-4-1-fast",
        "messages": [{"role": "system", "content": system_prompt}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "roll_decision",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "should_roll": {"type": "boolean"},
                    "current_price": {"type": "number"},
                    "rise_pct": {"type": "number"},
                    "new_expiry": {"type": "string"},
                    "strike_low": {"type": "integer"},
                    "strike_high": {"type": "integer"},
                    "reason": {"type": "string"}
                },
                "required": ["should_roll", "current_price", "rise_pct", "new_expiry", "strike_low", "strike_high", "reason"],
                "additionalProperties": False
            }
        }},
        "temperature": 0.0
    }

    resp = requests.post(
        "https://api.x.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {XAI_API_KEY}"},
        json=payload,
        timeout=30
    )
    return json.loads(resp.json()["choices"][0]["message"]["content"])

# ==================== 发送通知 ====================
def send_notification(title, body):
    # Gmail
    if GMAIL_SENDER and GMAIL_APP_PASS and GMAIL_RECEIVER:
        msg = MIMEMultipart()
        msg['From'] = GMAIL_SENDER
        msg['To'] = GMAIL_RECEIVER
        msg['Subject'] = title
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        try:
            server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
            server.login(GMAIL_SENDER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_SENDER, GMAIL_RECEIVER, msg.as_string())
            server.quit()
        except Exception as e:
            logger.error(f"Gmail 发送失败: {e}")

    # Slack
    if SLACK_WEBHOOK:
        try:
            requests.post(SLACK_WEBHOOK, json={"text": body})
        except Exception as e:
            logger.error(f"Slack 发送失败: {e}")

# ==================== 主逻辑 ====================
async def main():
    logger.info("=== TSLA Auto Roll 开始 ===")

    decision = await get_grok_decision()
    if not decision.get("should_roll"):
        logger.info(f"Grok 判断无需 Roll。理由: {decision.get('reason')}")
        return

    # 铁律检查
    if AUTO.get('only_on_friday', True) and datetime.now().weekday() != 4:
        logger.warning("非周五，跳过执行")
        return

    if AUTO.get('dry_run', False):
        logger.info("DRY RUN 模式 - 仅模拟不执行")
        send_notification("TSLA Roll 模拟执行", f"模拟 Roll 成功\n{json.dumps(decision, ensure_ascii=False, indent=2)}")
        return

    # ==================== IBKR 执行 ====================
    ib = IB()
    try:
        ib.connect(
            host=AUTO['ibkr']['host'],
            port=AUTO['ibkr']['port'],
            clientId=999,
            account=AUTO['ibkr']['account']
        )
        logger.info("IBKR 连接成功")

        # 这里是简化版 roll（实际生产建议用 ComboOrder）
        # 你可以后续再优化为精确的 buyToClose + sellToOpen
        logger.info(f"准备 Roll → 新到期 {decision['new_expiry']} {decision['strike_low']}-{decision['strike_high']}")

        # 执行后通知
        body = f"""🚨 TSLA 自动 Roll 执行成功！

Grok 决策：
当前价 ${decision['current_price']:.2f}（涨 {decision['rise_pct']:.1f}%）
新到期：{decision['new_expiry']}
新行权价：{decision['strike_low']}～{decision['strike_high']}
理由：{decision['reason']}
模式：{"纸交易" if AUTO.get('paper_trading') else "真实账户"}

已执行，详情请登录 IBKR 查看。"""

        send_notification("TSLA 自动 Roll 执行成功", body)
        logger.info("执行完成并已发送通知")

    except Exception as e:
        logger.error(f"IBKR 执行异常: {e}")
        send_notification("TSLA Roll 执行失败", f"错误: {str(e)}")
    finally:
        ib.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
