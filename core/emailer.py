"""Gmail SMTP alert emails (HTML). Credentials come from env vars / secrets:
GMAIL_USER, GMAIL_APP_PASSWORD, ALERT_TO."""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SEV_COLOR = {3: "#c0392b", 2: "#e67e22", 1: "#2980b9", 0: "#27ae60"}
SEV_LABEL = {3: "EXTREME", 2: "ALERT", 1: "SIGNAL", 0: "TARGET HIT"}


def build_html(alerts, headline_prices):
    rows = ""
    for a in sorted(alerts, key=lambda x: -x["severity"]):
        c = SEV_COLOR.get(a["severity"], "#555")
        rows += f"""
        <tr><td style="padding:10px;border-bottom:1px solid #eee">
          <span style="background:{c};color:#fff;padding:2px 8px;border-radius:4px;
           font-size:11px;font-weight:bold">{SEV_LABEL.get(a['severity'], 'INFO')}</span>
          <div style="font-weight:bold;margin:6px 0 4px">{a['title']}</div>
          <div style="color:#444;font-size:13px">{a['advice']}</div>
        </td></tr>"""
    prices = " &nbsp;|&nbsp; ".join(headline_prices)
    return f"""
    <div style="font-family:Segoe UI,Arial,sans-serif;max-width:640px;margin:auto">
      <h2 style="color:#1a237e;margin-bottom:4px">📊 Market Sentinel</h2>
      <div style="color:#666;font-size:12px;margin-bottom:14px">{prices}</div>
      <table style="width:100%;border-collapse:collapse">{rows}</table>
      <p style="color:#999;font-size:11px;margin-top:16px">
        Educational signals, not financial advice. Sent by your Market Sentinel
        GitHub Actions workflow.</p>
    </div>"""


def send_alert_email(alerts, headline_prices, subject=None):
    # sanitize: app passwords are 16 letters — strip whitespace/newlines that
    # sneak in via copy-paste, and the display-only spaces Google shows
    user = os.environ["GMAIL_USER"].strip()
    pwd = os.environ["GMAIL_APP_PASSWORD"].strip().replace(" ", "")
    to = os.environ.get("ALERT_TO", user).strip()
    if "@" not in user:
        user += "@gmail.com"
    if len(pwd) != 16:
        print(f"WARNING: app password is {len(pwd)} chars after cleanup — "
              "a Gmail app password is exactly 16. Re-check the secret.")

    top = max(a["severity"] for a in alerts)
    subject = subject or (f"{'🚨' if top >= 3 else '⚠️' if top >= 2 else '🔔'} "
                          f"Market Sentinel: {alerts[0]['title'][:80]}"
                          + (f" (+{len(alerts)-1} more)" if len(alerts) > 1 else ""))

    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText("\n\n".join(f"[{SEV_LABEL.get(a['severity'])}] {a['title']}\n{a['advice']}"
                                    for a in alerts), "plain"))
    msg.attach(MIMEText(build_html(alerts, headline_prices), "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(user, pwd)
            s.sendmail(user, [to], msg.as_string())
    except smtplib.SMTPAuthenticationError:
        # safe diagnostics — no secret values are printed
        local, _, domain = user.partition("@")
        print("AUTH DEBUG:"
              f" user_local_len={len(local)}"
              f" user_domain={domain or 'MISSING'}"
              f" user_first_char={local[:1]}"
              f" pwd_len={len(pwd)}"
              f" pwd_all_lowercase_letters={pwd.isalpha() and pwd.islower()}")
        print("A Gmail app password is 16 lowercase letters, and must be "
              "generated on the SAME account as GMAIL_USER (with 2FA enabled).")
        raise
