import { expect, test } from "@playwright/test";

test("reader can sort and fuzzy-search the Case feed", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Справи, за якими варто стежити" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Shkandal" })).toBeVisible();
  await expect(page.getByText("Тестова подія").first()).toBeVisible();
  await expect(page.getByText(/case-e2e|e2e-public-case/)).toHaveCount(0);
  await page.getByRole("link", { name: "останні оновлення" }).click();
  await expect(page).toHaveURL(/sort=latest/);

  await page.getByLabel("Пошук справи за назвою").fill("корупційна");
  await page.getByRole("button", { name: "знайти" }).click();
  await expect(page.getByRole("heading", { name: "Корупційна справа для перевірки" })).toBeVisible();
});

test("reader can inspect Case provenance and navigate to an Entity", async ({ page }) => {
  await page.goto("/cases/e2e-public-case");

  await expect(page.getByRole("heading", { name: "Джерела справи" })).toBeVisible();
  await expect(page.getByTitle(/Українська правда/)).toBeVisible();
  await page.getByText("1 джерело події").click();
  await expect(page.getByRole("heading", { name: "Джерельний матеріал для перевірки" })).toBeVisible();

  await page.getByRole("link", { name: /Тестова особа/ }).click();
  await expect(page.getByRole("heading", { name: "Тестова особа" })).toBeVisible();
});

test("Case view is counted once per browser session", async ({ page }) => {
  await page.goto("/cases/e2e-public-case");
  await page.reload();

  const keys = await page.evaluate(() => Object.keys(sessionStorage));
  expect(keys.filter((key) => key === "shkandal:viewed:e2e-public-case")).toHaveLength(1);
});
