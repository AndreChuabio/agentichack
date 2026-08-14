import { expect, test } from "@playwright/test";

/**
 * Proves the suite is pointed at Merit before any other test's result means
 * anything.
 *
 * Playwright's `reuseExistingServer` adopts whatever is already listening on
 * the port. On a machine running a second Next project on 3000, the whole suite
 * runs against that stranger's app: assertions about Merit's copy fail for the
 * wrong reason, and any assertion loose enough to hold on someone else's 404
 * page passes and is counted as evidence. That happened -- a run reported one
 * green test against an app called Storysofar.
 *
 * This test is cheap and unambiguous, and a failure here means every other
 * result in the run should be discarded rather than debugged.
 */
test("the server under test is actually Merit", async ({ page, baseURL }) => {
  const response = await page.goto("/");
  expect(
    response?.ok(),
    `no page served at ${baseURL} -- is the dev server up?`,
  ).toBeTruthy();

  const title = await page.title();
  const html = await page.content();
  const looksLikeMerit =
    /merit/i.test(title) || /O-1A|Extraordinary ability/i.test(html);

  expect(
    looksLikeMerit,
    `${baseURL} served "${title}", which is not Merit. Something else is on ` +
      `that port and reuseExistingServer adopted it. Re-run with ` +
      `PLAYWRIGHT_PORT set to a free port; every other result in this run is ` +
      `meaningless until this passes.`,
  ).toBeTruthy();
});
