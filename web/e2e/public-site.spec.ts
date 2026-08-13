import { expect, test } from "@playwright/test";

test("an unknown slug renders the not-found page", async ({ page }) => {
  const response = await page.goto("/u/definitely-not-a-real-slug-xyz");
  expect(response?.status()).toBe(404);
});
