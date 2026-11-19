"""Writes workflow.json: the Document Desk intake flow for n8n.  python n8n/build_workflow.py > n8n/workflow.json"""
import json, uuid
def node(name, type_, v, pos, params=None, **kw):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "dd" + name)), "name": name, "type": type_, "typeVersion": v, "position": pos, "parameters": params or {}, **kw}

PREPARE = """// Test inbox: JSON with content_base64.  Mailbox trigger: the attachment arrives as a binary file. Both become the same request.
const item = $input.first();
const b = item.json.body && typeof item.json.body === 'object' ? item.json.body : item.json;
let filename = b.filename, content = b.content_base64, source = b.source || 'n8n';
if (!content && item.binary) {
  const key = Object.keys(item.binary)[0];
  const buf = await this.helpers.getBinaryDataBuffer(0, key);
  content = buf.toString('base64'); filename = filename || item.binary[key].fileName || 'document'; source = 'mailbox';
}
if (!content) throw new Error('No file found on this item');
return [{ json: { filename, content_base64: content, source } }];"""

def cond(field, val): return {"options": {"caseSensitive": True, "typeValidation": "loose", "version": 2}, "combinator": "and", "conditions": [{"leftValue": "={{ $json.status }}", "rightValue": val, "operator": {"type": "string", "operation": "equals"}}]}
nodes = [
 node("New document (test inbox)", "n8n-nodes-base.webhook", 2, [0, 120], {"httpMethod": "POST", "path": "incoming-document", "responseMode": "responseNode", "options": {}}, webhookId="d0c0ffee-1111-4222-8333-444455556666"),
 node("Mailbox with invoices (production)", "n8n-nodes-base.emailReadImap", 2, [0, 320], {"mailbox": "INBOX", "postProcessAction": "read", "format": "resolved", "options": {"downloadAttachments": True}}, disabled=True,
      notes="Switch this on and add the IMAP login for the mailbox invoices are sent to. Each PDF or image attachment goes through the same flow as the test inbox on the left."),
 node("Prepare document", "n8n-nodes-base.code", 2, [260, 220], {"jsCode": PREPARE}),
 node("Send to Document Desk", "n8n-nodes-base.httpRequest", 4.2, [520, 220], {
     "method": "POST", "url": "http://127.0.0.1:8796/api/inbound", "sendHeaders": True,
     "headerParameters": {"parameters": [{"name": "X-Inbound-Key", "value": "demo-key"}]},
     "sendBody": True, "specifyBody": "json", "jsonBody": "={{ JSON.stringify($json) }}", "options": {"timeout": 120000}}),
 node("How did it read?", "n8n-nodes-base.switch", 3.2, [780, 200], {"rules": {"values": [
     {"conditions": cond("status", "ready"), "renameOutput": True, "outputKey": "Ready"},
     {"conditions": cond("status", "review"), "renameOutput": True, "outputKey": "Needs a person"}]},
     "options": {"fallbackOutput": "extra", "renameFallbackOutput": "Could not read"}}),
 node("Ready for approval", "n8n-nodes-base.noOp", 1, [1060, 40], {}, notes="Every check passed. It waits in the inbox for a one-click approval."),
 node("Write review note", "n8n-nodes-base.set", 3.4, [1060, 220], {"assignments": {"assignments": [
     {"id": "a1", "name": "text", "type": "string", "value": "={{ 'Document ' + $json.id + ' from ' + ($json.supplier || 'an unknown supplier') + ' (total ' + $json.total + ') needs a person to check it. Open Document Desk, Needs review.' }}"}]}, "options": {}}),
 node("Post to chat", "n8n-nodes-base.httpRequest", 4.2, [1300, 220], {"method": "POST", "url": "http://127.0.0.1:8799/", "sendBody": True, "specifyBody": "json", "jsonBody": "={{ JSON.stringify({ text: $json.text }) }}", "options": {}},
      notes="Points at a local stand-in for a Slack incoming webhook. Replace the URL with a real one."),
 node("Could not read", "n8n-nodes-base.noOp", 1, [1060, 420], {}, notes="Nothing could be read (blank page, damaged file). A person opens it from the Failed filter."),
 node("Reply with result", "n8n-nodes-base.respondToWebhook", 1.1, [1540, 240], {"respondWith": "json", "responseBody": "={{ JSON.stringify($('Send to Document Desk').first().json) }}", "options": {}}),
]
def c(*t): return {"main": [[{"node": x, "type": "main", "index": 0} for x in t]]}
connections = {"New document (test inbox)": c("Prepare document"), "Mailbox with invoices (production)": c("Prepare document"), "Prepare document": c("Send to Document Desk"), "Send to Document Desk": c("How did it read?"),
 "How did it read?": {"main": [[{"node": "Ready for approval", "type": "main", "index": 0}], [{"node": "Write review note", "type": "main", "index": 0}], [{"node": "Could not read", "type": "main", "index": 0}]]},
 "Ready for approval": c("Reply with result"), "Write review note": c("Post to chat"), "Post to chat": c("Reply with result"), "Could not read": c("Reply with result")}
print(json.dumps({"name": "Documents to review: Fernhill Document Desk", "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1"}}, indent=1))
