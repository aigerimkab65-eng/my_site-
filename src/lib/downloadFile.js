/**
 * Download a binary response (PDF, etc.) with session cookies.
 * Filename is taken from Content-Disposition when present.
 */
export async function downloadFile(url, options = {}) {
  const { fallbackName = "download.bin", localizeError } = options;
  let response;
  try {
    response = await fetch(url, {
      credentials: "include",
      ...options.fetchOptions,
    });
  } catch (_) {
    throw new Error(
      typeof localizeError === "function"
        ? localizeError("Сервер не запущен. Открой файл «Start Site.command» и попробуй снова.")
        : "Сервер не запущен. Открой файл «Start Site.command» и попробуй снова."
    );
  }

  if (!response.ok) {
    let message = "Не удалось скачать файл";
    try {
      const data = await response.json();
      if (data && data.error) message = data.error;
    } catch (_) {
      // non-JSON error body
    }
    throw new Error(
      typeof localizeError === "function" ? localizeError(message) : message
    );
  }

  const blob = await response.blob();
  const header = response.headers.get("Content-Disposition") || "";
  const name = filenameFromContentDisposition(header) || fallbackName;
  const objectUrl = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = name;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
  return name;
}

export function filenameFromContentDisposition(header) {
  if (!header) return "";
  const utf = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (utf) {
    try {
      return decodeURIComponent(utf[1].trim().replace(/["']/g, ""));
    } catch (_) {
      return utf[1].trim().replace(/["']/g, "");
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1].trim() : "";
}
