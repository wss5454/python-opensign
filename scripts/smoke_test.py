"""Quick end-to-end smoke test against a running server."""

import base64
import json
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image

BASE = "http://127.0.0.1:8000"


def call(method, path, data=None, headers=None):
    headers = dict(headers or {})
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        if "application/json" in resp.headers.get("content-type", ""):
            return resp.status, json.loads(body)
        return resp.status, body


def main():
    _, health = call("GET", "/api/health")
    print("health", health)

    boundary = "----WallaceSignBoundary7MA4YWxk"
    pdf = Path("sample_contract.pdf").read_bytes()
    signers = json.dumps(
        [
            {
                "name": "Alice Signer",
                "email": "alice@example.com",
                "role": "signer",
                "order_index": 0,
                "widgets": [
                    {"type": "signature", "page": 1, "x": 20, "y": 75, "w": 30, "h": 10}
                ],
            }
        ]
    )
    fields = {
        "title": "Sample Contract",
        "description": "Demo signing with widgets",
        "sequential": "false",
        "signers_json": signers,
    }
    parts = []
    for key, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f'filename="sample_contract.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
        + pdf
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    _, doc = call(
        "POST",
        "/api/documents",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    print("created", doc["id"], doc["status"], doc["document_url"])
    print("sign_url", doc["signers"][0]["sign_url"])
    print("widgets", doc["signers"][0]["widgets"])
    doc_id = doc["id"]
    widget_id = doc["signers"][0]["widgets"][0]["id"]

    _, sent = call("POST", f"/api/documents/{doc_id}/send")
    print("sent", sent["status"])
    token = sent["signers"][0]["access_token"]

    img = Image.new("RGBA", (200, 80), (255, 255, 255, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    payload = json.dumps(
        {
            "signatures": [{"widget_id": widget_id, "signature_data": data_url}],
            "consent": True,
        }
    ).encode()
    _, signed = call(
        "POST",
        f"/api/sign/{token}",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    print(
        "signed",
        signed["status"],
        [(s["name"], s["status"]) for s in signed["signers"]],
    )


if __name__ == "__main__":
    main()
