from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 9999

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Fingerprint Debug</title>
<style>
body { font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 20px; }
.box { background: #161b22; padding: 12px; margin: 10px 0; border-radius: 8px; border: 1px solid #30363d; }
h2 { color: #58a6ff; }
</style>
</head>
<body>

<h1>Browser Fingerprint Debug</h1>
<div id="output"></div>

<script>
function add(title, value) {
  const div = document.createElement("div");
  div.className = "box";
  div.innerHTML = `<h2>${title}</h2><pre>${value}</pre>`;
  document.getElementById("output").appendChild(div);
}

add("User Agent", navigator.userAgent);

add("Viewport", `
innerWidth: ${window.innerWidth}
innerHeight: ${window.innerHeight}
screen.width: ${screen.width}
screen.height: ${screen.height}
devicePixelRatio: ${window.devicePixelRatio}
`);

add("Timezone", Intl.DateTimeFormat().resolvedOptions().timeZone);

add("Language", navigator.language);

add("Platform", navigator.platform);

add("CPU cores", navigator.hardwareConcurrency);

add("Webdriver", navigator.webdriver);

function getWebGL() {
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl");
    const debug = gl.getExtension('WEBGL_debug_renderer_info');
    return gl.getParameter(debug.UNMASKED_RENDERER_WEBGL);
  } catch {
    return "N/A";
  }
}
add("WebGL Renderer", getWebGL());

function canvasFP() {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  ctx.fillText("test", 10, 10);
  return canvas.toDataURL().slice(0, 80);
}
add("Canvas FP", canvasFP());

add("Cookies", document.cookie || "brak");

</script>

</body>
</html>
"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(HTML.encode("utf-8"))

httpd = HTTPServer(("0.0.0.0", PORT), Handler)
print(f"Serwer działa: http://localhost:{PORT}")
httpd.serve_forever()