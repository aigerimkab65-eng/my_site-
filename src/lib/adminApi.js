let csrfToken = "";

export function getCsrfToken() {
  return csrfToken;
}

export function setCsrfToken(token) {
  csrfToken = typeof token === "string" ? token : "";
}

export function clearCsrfToken() {
  csrfToken = "";
}

function rememberCsrfFromPayload(data) {
  if (data && typeof data.csrfToken === "string" && data.csrfToken) {
    csrfToken = data.csrfToken;
  }
}

export class AdminApiError extends Error {
  constructor(message, { status = 0, data = null } = {}) {
    super(message);
    this.name = "AdminApiError";
    this.status = status;
    this.data = data;
  }
}

export async function adminApi(url, options = {}, localizeError) {
  const method = String(options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method) && csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }

  let response;
  try {
    response = await fetch(url, {
      credentials: "include",
      ...options,
      headers,
    });
  } catch (err) {
    console.error("[adminApi] network error", url, method, err);
    throw new AdminApiError(
      "Сервер не запущен. Открой файл «Start Site.command» и попробуй снова.",
      { status: 0 }
    );
  }

  const data = await response.json().catch(() => ({}));
  if (response.ok) {
    rememberCsrfFromPayload(data);
    return data;
  }

  const fallback = "Не получилось сохранить";
  const message = data.error || fallback;
  const localized =
    typeof localizeError === "function" ? localizeError(message) : message;
  console.error("[adminApi] request failed", {
    url,
    method,
    status: response.status,
    error: data.error || null,
  });
  throw new AdminApiError(localized, { status: response.status, data });
}
