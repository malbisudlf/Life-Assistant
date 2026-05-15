import os, json, urllib.request, urllib.error

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_KEY"]
hdrs = {
    "apikey": key,
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

def req(method, path, data=None):
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(f"{url}/rest/v1/{path}", data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print("ERROR", e.code, e.read())
        return []

clients = req("GET", "training_clients?limit=1&order=created_at.asc")
cid = clients[0]["id"]

latest = req("GET", f"training_sessions?client_id=eq.{cid}&order=created_at.desc&limit=1&select=id,date,duration_hours,created_at")
if not latest:
    print("No sessions found")
    exit(1)
s = latest[0]
print(f"Borrando: {s['date']} {s['duration_hours']}h (created_at: {s['created_at']})")
req("DELETE", f"training_sessions?id=eq.{s['id']}")
print("Done!")
