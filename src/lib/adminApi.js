export async function adminApi(url, options = {}, localizeError) {
  let response;
  try {
    response = await fetch(url, {
      credentials: "include",
      ...options,
    });
  } catch (_) {
    throw new Error(
      "Сервер не запущен. Открой файл «Start Site.command» и попробуй снова."
    );
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const fallback = "Не получилось сохранить";
    const message = data.error || fallback;
    throw new Error(
      typeof localizeError === "function" ? localizeError(message) : message
    );
  }
  return data;
}
