"""E-mail delivery + templating for Mira (GV TECH).

The transport is plain ``smtplib`` configured entirely from environment
variables so the same code runs in dev (no SMTP) and production (real SMTP).

Env vars
--------
SMTP_HOST      SMTP server hostname. If absent → dev mode (no real send).
SMTP_PORT      SMTP port (default 587).
SMTP_USER      Login username (optional; if unset, no auth is attempted).
SMTP_PASSWORD  Login password.
SMTP_FROM      "From" address (default: SMTP_USER or "no-reply@gvtechdrc.com").
SMTP_TLS       "true"/"false". true → STARTTLS on a plain connection.
               If the port is 465 an implicit SSL connection is used instead.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

logger = logging.getLogger(__name__)


def _env_truthy(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _smtp_configured() -> bool:
    """Return True when a real SMTP host is configured (production mode)."""
    return bool(os.getenv("SMTP_HOST", "").strip())


def send_email(to: str, subject: str, html: str, text: Optional[str] = None) -> bool:
    """Send an HTML e-mail via SMTP.

    Returns ``True`` when the message was handed off to an SMTP server, and
    ``False`` in dev mode (no ``SMTP_HOST``) or on any failure. Callers rely on
    the ``False`` return in dev to surface a reset link in the API response.

    The function never raises on transport errors — it logs and returns False so
    the calling endpoint can degrade gracefully.
    """
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        # Dev mode: don't crash, just log enough to test the flow manually.
        logger.warning(
            "[email_service] SMTP non configuré (SMTP_HOST absent) — e-mail NON envoyé.\n"
            "  → destinataire : %s\n  → sujet       : %s",
            to,
            subject,
        )
        print(
            f"[email_service][DEV] E-mail non envoyé (pas de SMTP_HOST). "
            f"to={to!r} subject={subject!r}"
        )
        return False

    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    from_addr = os.getenv("SMTP_FROM", "").strip() or user or "no-reply@gvtechdrc.com"
    use_tls = _env_truthy(os.getenv("SMTP_TLS"), default=True)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Mira — GV TECH", from_addr))
    msg["To"] = to
    # Plain-text fallback first, then the HTML alternative.
    msg.set_content(text or "Veuillez consulter cet e-mail dans un client compatible HTML.")
    msg.add_alternative(html, subtype="html")

    try:
        if port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
                if user:
                    server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.ehlo()
                if use_tls:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                    server.ehlo()
                if user:
                    server.login(user, password)
                server.send_message(msg)
        logger.info("[email_service] E-mail envoyé à %s (sujet: %s)", to, subject)
        return True
    except Exception as exc:  # noqa: BLE001 — transport must never crash the request
        logger.error("[email_service] Échec d'envoi à %s : %s", to, exc)
        print(f"[email_service] Échec d'envoi à {to!r}: {exc}")
        return False


def render_password_reset_email(name: str, reset_link: str) -> str:
    """Return a responsive, branded HTML e-mail for a password reset.

    Mira / GV TECH branding, French copy, a CTA button to ``reset_link``, a
    1-hour expiry notice, and a plain-text fallback link.
    """
    safe_name = (name or "").strip() or "à vous"
    preheader = "Réinitialisez votre mot de passe Mira — lien valable 1 heure."
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="x-apple-disable-message-reformatting" />
  <title>Réinitialisation de votre mot de passe</title>
</head>
<body style="margin:0;padding:0;background-color:#0b0f1a;background:#0b0f1a;">
  <span style="display:none!important;visibility:hidden;opacity:0;color:transparent;height:0;width:0;overflow:hidden;mso-hide:all;">{preheader}</span>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#0b0f1a;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;width:100%;background-color:#121829;border:1px solid #1f2940;border-radius:16px;overflow:hidden;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
          <!-- Header / brand -->
          <tr>
            <td style="padding:28px 32px 8px 32px;" align="left">
              <span style="display:inline-block;font-size:22px;font-weight:800;letter-spacing:0.5px;color:#ffffff;font-family:'Roboto Mono','Segoe UI',monospace;">
                Mira
              </span>
              <span style="display:inline-block;margin-left:8px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#4bff2a;vertical-align:middle;">
                GV&nbsp;TECH
              </span>
            </td>
          </tr>
          <!-- Accent bar -->
          <tr><td style="padding:0 32px;"><div style="height:3px;width:56px;background:#2a2aff;border-radius:3px;"></div></td></tr>
          <!-- Body -->
          <tr>
            <td style="padding:20px 32px 8px 32px;">
              <h1 style="margin:0 0 16px 0;font-size:24px;line-height:1.25;color:#ffffff;font-weight:700;">
                Réinitialisation de votre mot de passe
              </h1>
              <p style="margin:0 0 14px 0;font-size:15px;line-height:1.6;color:#c4ccdc;">
                Bonjour {safe_name},
              </p>
              <p style="margin:0 0 14px 0;font-size:15px;line-height:1.6;color:#c4ccdc;">
                Nous avons reçu une demande de réinitialisation du mot de passe de votre
                compte Mira. Cliquez sur le bouton ci-dessous pour choisir un nouveau mot de passe.
              </p>
            </td>
          </tr>
          <!-- CTA button -->
          <tr>
            <td align="center" style="padding:18px 32px 10px 32px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td align="center" style="border-radius:10px;background:#2a2aff;">
                    <a href="{reset_link}" target="_blank"
                       style="display:inline-block;padding:14px 30px;font-size:15px;font-weight:700;color:#ffffff;text-decoration:none;border-radius:10px;background:#2a2aff;">
                      Réinitialiser mon mot de passe
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <!-- Expiry note -->
          <tr>
            <td style="padding:10px 32px 0 32px;">
              <p style="margin:0 0 14px 0;font-size:13px;line-height:1.6;color:#8a93a6;">
                Ce lien est valable <strong style="color:#c4ccdc;">1 heure</strong>. Passé ce délai,
                vous devrez refaire une demande de réinitialisation.
              </p>
              <p style="margin:0 0 8px 0;font-size:13px;line-height:1.6;color:#8a93a6;">
                Si le bouton ne fonctionne pas, copiez-collez ce lien dans votre navigateur :
              </p>
              <p style="margin:0 0 18px 0;font-size:12px;line-height:1.5;word-break:break-all;">
                <a href="{reset_link}" target="_blank" style="color:#4bff2a;text-decoration:underline;">{reset_link}</a>
              </p>
              <p style="margin:0 0 6px 0;font-size:13px;line-height:1.6;color:#8a93a6;">
                Vous n'êtes pas à l'origine de cette demande ? Vous pouvez ignorer cet e-mail
                en toute sécurité, votre mot de passe restera inchangé.
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:22px 32px 28px 32px;border-top:1px solid #1f2940;">
              <p style="margin:0;font-size:12px;line-height:1.6;color:#6b7385;">
                Mira — édité par GV TECH ·
                <a href="https://gvtechdrc.com" target="_blank" style="color:#8a93a6;text-decoration:underline;">gvtechdrc.com</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def render_password_reset_text(name: str, reset_link: str) -> str:
    """Plain-text version of the reset e-mail (fallback for non-HTML clients)."""
    safe_name = (name or "").strip() or "à vous"
    return (
        f"Bonjour {safe_name},\n\n"
        "Nous avons reçu une demande de réinitialisation du mot de passe de votre "
        "compte Mira.\n\n"
        "Ouvrez ce lien pour choisir un nouveau mot de passe (valable 1 heure) :\n"
        f"{reset_link}\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail : "
        "votre mot de passe restera inchangé.\n\n"
        "—\n"
        "Mira — édité par GV TECH · gvtechdrc.com\n"
    )


def send_quota_alert_email(
    client_email: str,
    client_name: str,
    percent_used: int,
    quota_used: int,
    quota_total: int,
) -> bool:
    """Send a quota usage alert email at 80% and 95% thresholds."""
    safe_name = (client_name or "").strip() or "à vous"
    color = "#ff9900" if percent_used < 95 else "#ff3333"
    subject = f"[Mira] Alerte quota : {percent_used}% utilisé"
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <title>Alerte quota Mira</title>
</head>
<body style="margin:0;padding:0;background:#0b0f1a;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#0b0f1a;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
               style="max-width:560px;background:#121829;border:1px solid #1f2940;border-radius:16px;overflow:hidden;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
          <tr>
            <td style="padding:28px 32px 8px 32px;">
              <span style="font-size:22px;font-weight:800;color:#fff;font-family:'Roboto Mono',monospace;">Mira</span>
              <span style="margin-left:8px;font-size:12px;font-weight:700;text-transform:uppercase;color:#4bff2a;">GV TECH</span>
            </td>
          </tr>
          <tr><td style="padding:0 32px;"><div style="height:3px;width:56px;background:{color};border-radius:3px;"></div></td></tr>
          <tr>
            <td style="padding:20px 32px 28px 32px;">
              <h1 style="margin:0 0 16px;font-size:22px;color:#fff;font-weight:700;">
                Alerte quota — {percent_used}% utilisé
              </h1>
              <p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#c4ccdc;">
                Bonjour {safe_name},
              </p>
              <p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#c4ccdc;">
                Vous avez utilisé <strong style="color:{color};">{percent_used}%</strong> de votre quota mensuel
                (<strong>{quota_used:,}</strong> / <strong>{quota_total:,}</strong> requêtes).
              </p>
              <p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:#c4ccdc;">
                Pour éviter toute interruption de service, pensez à passer à un plan supérieur
                depuis votre espace client.
              </p>
              <p style="margin:0;font-size:12px;color:#6b7385;">
                Mira — édité par GV TECH ·
                <a href="https://gvtechdrc.com" style="color:#8a93a6;">gvtechdrc.com</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
    text = (
        f"Bonjour {safe_name},\n\n"
        f"Vous avez utilisé {percent_used}% de votre quota mensuel "
        f"({quota_used}/{quota_total} requêtes).\n\n"
        "Pour éviter toute interruption, passez à un plan supérieur depuis votre espace client.\n\n"
        "— Mira, GV TECH · gvtechdrc.com\n"
    )
    return send_email(client_email, subject, html, text)
