# n8n version

`workflow.json` is the intake flow: test inbox (webhook) or mailbox (disabled until a login is added) -> Code step -> HTTP Request to Document Desk -> Switch (ready / needs review / could not read) -> chat alert.

1. Run Document Desk with `INBOUND_KEY=demo-key` on port 8796 (or edit the URL and key in the "Send to Document Desk" node).
2. In n8n, Import from file -> `workflow.json`, then Publish.
3. `python n8n/fake_slack.py 8799` starts a local stand-in for a Slack incoming webhook (swap the URL for a real one).
4. Send a document: POST `{"filename": "x.pdf", "content_base64": "..."}` to `/webhook/incoming-document`.

`python n8n/build_workflow.py > n8n/workflow.json` regenerates the file. The local file trigger is not available in n8n 2.x by default, so the production trigger is an IMAP mailbox with attachments.
