// @ts-check
import { test, expect } from "@playwright/test";

test("lead modal saves order before WhatsApp", async ({ page }) => {
  await page.addInitScript(() => {
    window.__waOpened = false;
    window.__lastWaUrl = "";
    window.open = (url) => {
      const state = { href: String(url || ""), closed: false };
      if (state.href && state.href !== "about:blank") {
        window.__lastWaUrl = state.href;
        window.__waOpened = true;
      }
      return {
        get closed() {
          return state.closed;
        },
        location: {
          get href() {
            return state.href;
          },
          set href(value) {
            state.href = String(value || "");
            if (state.href && state.href !== "about:blank") {
              window.__lastWaUrl = state.href;
              window.__waOpened = true;
            }
          },
        },
        close() {
          state.closed = true;
        },
      };
    };
  });

  const suffix = String(Date.now()).slice(-7);
  const phone = `700${suffix}`.slice(0, 10);

  await page.goto("/");
  await page.locator("#services-toggle").click();

  const orderBtn = page.locator(".js-wa-order").first();
  await expect(orderBtn).toHaveAttribute("type", "button");
  await expect(orderBtn).not.toHaveAttribute("href");

  await orderBtn.click();

  await expect(page.locator("#lead-modal")).toBeVisible();
  await page.locator("#lead-name").fill("E2E Test");
  await page.locator("#lead-phone").fill(phone);

  const orderResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/orders") &&
      response.request().method() === "POST"
  );

  await page.locator("#lead-submit").click();

  const response = await orderResponse;
  // 201 = new order, 200 = idempotent replay (same key / soft dedupe).
  expect([200, 201]).toContain(response.status());
  const body = await response.json();
  expect(body.clientName).toBe("E2E Test");
  expect(String(body.clientPhone || "").replace(/\D+/g, "")).toContain(
    phone.slice(-7)
  );
  expect(body.priceFrom).toBe(25000);

  await expect.poll(() => page.evaluate(() => window.__waOpened)).toBe(true);
  const waUrl = await page.evaluate(() => window.__lastWaUrl || "");
  expect(waUrl).toContain("wa.me/77007002132");
  expect(waUrl).toContain("text=");
  const text = decodeURIComponent(waUrl.split("text=")[1] || "");
  expect(text).toMatch(/25000|25[\s\u00a0]?000/);
  expect(text).toContain("E2E Test");
});
