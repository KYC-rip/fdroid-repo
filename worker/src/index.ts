export interface Env {
  REPO_BUCKET: R2Bucket;
}

const INDEX_HTML_CSP =
  "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

function contentTypeFor(key: string): string {
  if (key.endsWith(".html")) return "text/html; charset=utf-8";
  if (key.endsWith(".json")) return "application/json; charset=utf-8";
  if (key.endsWith(".apk")) return "application/vnd.android.package-archive";
  if (key.endsWith(".jar")) return "application/java-archive";
  if (key.endsWith(".png")) return "image/png";
  if (key.endsWith(".jpg") || key.endsWith(".jpeg")) return "image/jpeg";
  if (key.endsWith(".webp")) return "image/webp";
  if (key.endsWith(".svg")) return "image/svg+xml";
  if (key.endsWith(".asc") || key.endsWith(".txt")) return "text/plain; charset=utf-8";
  return "application/octet-stream";
}

function cacheControlFor(key: string): string {
  if (key.endsWith(".apk") || key.endsWith(".apk.asc")) {
    return "public, max-age=31536000, immutable";
  }
  if (
    key === "index.html" ||
    key.endsWith("index-v2.json") ||
    key.endsWith("index-v1.jar") ||
    key.endsWith("index-v1.json") ||
    key.endsWith("entry.jar") ||
    key.endsWith("entry.json") ||
    key.includes("/status/")
  ) {
    return "public, max-age=300";
  }
  return "public, max-age=86400";
}

function parseRange(header: string | null, size: number): { offset: number; length: number } | null {
  if (!header) return null;
  const m = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!m) return null;
  const [, startStr, endStr] = m;
  if (!startStr && !endStr) return null;
  let start: number;
  let end: number;
  if (!startStr) {
    const suffix = Number(endStr);
    if (!Number.isFinite(suffix) || suffix <= 0) return null;
    start = Math.max(0, size - suffix);
    end = size - 1;
  } else {
    start = Number(startStr);
    end = endStr ? Math.min(size - 1, Number(endStr)) : size - 1;
  }
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || start > end || start >= size) {
    return null;
  }
  return { offset: start, length: end - start + 1 };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method Not Allowed", { status: 405, headers: { Allow: "GET, HEAD" } });
    }

    const url = new URL(request.url);
    let rawPath: string;
    try {
      rawPath = decodeURIComponent(url.pathname);
    } catch {
      return new Response("Bad Request", { status: 400 });
    }

    if (rawPath.includes("\0") || rawPath.split("/").some((seg) => seg === "..")) {
      return new Response("Bad Request", { status: 400 });
    }

    const key =
      rawPath === "/" || rawPath === "/index.html" || rawPath === "/repo" || rawPath === "/repo/"
        ? "index.html"
        : rawPath.replace(/^\/+/, "");

    const headObj = await env.REPO_BUCKET.head(key);
    if (!headObj) {
      return new Response("Not Found", { status: 404 });
    }

    const headers = new Headers();
    headers.set("Content-Type", headObj.httpMetadata?.contentType || contentTypeFor(key));
    headers.set("Cache-Control", cacheControlFor(key));
    headers.set("ETag", headObj.httpEtag);
    headers.set("Accept-Ranges", "bytes");
    headers.set("X-Content-Type-Options", "nosniff");
    headers.set("Referrer-Policy", "no-referrer");
    if (key.endsWith(".html")) {
      headers.set("Content-Security-Policy", INDEX_HTML_CSP);
    }

    const ifNoneMatch = request.headers.get("If-None-Match");
    if (ifNoneMatch && (ifNoneMatch === headObj.httpEtag || ifNoneMatch === `W/${headObj.httpEtag}`)) {
      return new Response(null, { status: 304, headers });
    }

    if (request.method === "HEAD") {
      headers.set("Content-Length", String(headObj.size));
      return new Response(null, { status: 200, headers });
    }

    const rangeHeader = request.headers.get("Range");
    if (rangeHeader) {
      const range = parseRange(rangeHeader, headObj.size);
      if (!range) {
        headers.set("Content-Range", `bytes */${headObj.size}`);
        return new Response("Range Not Satisfiable", { status: 416, headers });
      }
      const obj = await env.REPO_BUCKET.get(key, { range });
      if (!obj) return new Response("Not Found", { status: 404 });
      headers.set("Content-Range", `bytes ${range.offset}-${range.offset + range.length - 1}/${headObj.size}`);
      headers.set("Content-Length", String(range.length));
      return new Response(obj.body, { status: 206, headers });
    }

    const obj = await env.REPO_BUCKET.get(key);
    if (!obj) return new Response("Not Found", { status: 404 });
    headers.set("Content-Length", String(obj.size));
    return new Response(obj.body, { status: 200, headers });
  },
};
