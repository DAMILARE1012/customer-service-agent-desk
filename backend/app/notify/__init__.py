"""Reaching people who aren't looking at a screen: email (SMTP) and a chat webhook (Slack, Mattermost, Teams…).

Both are optional. With SMTP_HOST empty, emails are logged instead of sent; with ALERT_WEBHOOK_URL empty,
no webhook is called. Locally, `npm run infra:up` starts Mailpit, which catches every email in a web
inbox at http://localhost:8025.
"""
