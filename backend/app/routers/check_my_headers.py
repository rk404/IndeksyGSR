from flask import Flask, request

app = Flask(__name__)

@app.route("/")
def show_headers():
    result = []

    result.append("=== HEADERS ===")
    for header, value in request.headers.items():
        result.append(f"{header}: {value}")

    result.append("\n=== OTHER INFO ===")
    result.append(f"IP: {request.remote_addr}")
    result.append(f"Method: {request.method}")
    result.append(f"URL: {request.url}")

    return "<br>".join(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9990)