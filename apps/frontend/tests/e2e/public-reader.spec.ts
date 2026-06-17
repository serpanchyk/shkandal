import { expect, test } from "@playwright/test";

test("reader can sort and fuzzy-search the Case feed", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Справи, за якими варто стежити" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Shkandal" })).toBeVisible();
  await expect(page.getByText("Тестова подія").first()).toBeVisible();
  await expect(page.getByText(/case-e2e|e2e-public-case/)).toHaveCount(0);
  await expect(page.locator('[data-case-variant="lead"]')).toHaveCount(1);
  await expect(page.locator('[data-case-variant="supporting"]')).toHaveCount(4);
  await expect(page.locator('[data-case-variant="list"]')).toHaveCount(15);
  await page.getByRole("link", { name: "останні оновлення" }).click();
  await expect(page).toHaveURL(/sort=latest/);

  await page.getByLabel("Пошук справи за назвою").fill("корупційна");
  await page.getByRole("button", { name: "знайти" }).click();
  await expect(page.getByRole("heading", { name: "Корупційна справа для перевірки" })).toBeVisible();
  await expect(page.locator('[data-case-variant="lead"]')).toHaveCount(0);
  await expect(page.locator('[data-case-variant="list"]')).toHaveCount(1);
});

test("reader can page through the Case feed without the featured layout repeating", async ({
  page,
}) => {
  await page.goto("/?sort=latest");

  const pagination = page.getByRole("navigation", { name: "Сторінки" });
  await expect(pagination.getByRole("link", { name: "1", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(pagination.locator(".paginationEllipsis")).toHaveCount(1);
  await expect(pagination.getByRole("link", { name: "9", exact: true })).toBeVisible();
  await pagination.getByRole("link", { name: "2", exact: true }).click();

  await expect(page).toHaveURL(/sort=latest.*page=2/);
  await expect(page.locator('[data-case-variant="lead"]')).toHaveCount(0);
  await expect(page.locator('[data-case-variant="supporting"]')).toHaveCount(0);
  await expect(page.locator('[data-case-variant="list"]')).toHaveCount(20);
  await expect(pagination.getByRole("link", { name: "2", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("reader can inspect the global project explanation", async ({ page }) => {
  await page.goto("/");

  const footer = page.getByRole("contentinfo");
  await expect(footer.getByText(/Сторінки формуються автоматично/)).toBeVisible();
  await expect(footer.getByRole("link", { name: "GitHub ↗" })).toHaveAttribute(
    "href",
    "https://github.com/serpanchyk/shkandal",
  );
  await expect(
    footer.getByRole("link", {
      name: "Маєте ідеї або знайшли ваду? Доєднуйтесь до спільноти у WhatsApp.",
    }),
  ).toHaveAttribute("href", "https://chat.whatsapp.com/GKLJlgZ5Fh8Fp4WGc6ThB6");
  await expect(
    footer.getByRole("link", { name: "Розробник: Антон Михальчук." }),
  ).toHaveAttribute("href", "https://www.linkedin.com/in/anton-mykhalchuk/");
  await expect(footer.getByRole("link", { name: /Катедри систем штучного інтелекту/ })).toHaveAttribute(
    "href",
    "https://aidept.com.ua/",
  );
  await expect(footer.getByRole("link", { name: "Lapathoniia" })).toHaveAttribute(
    "href",
    "https://lapathoniia.top/",
  );

  await footer.getByRole("link", { name: "Про Шкандаль" }).click();
  await expect(page).toHaveURL(/\/about$/);
  await expect(page.getByRole("heading", { name: "Як читати досьє" })).toBeVisible();
});

test("reader can inspect Case provenance and navigate to an Entity", async ({ page }) => {
  await page.goto("/cases/e2e-public-case");

  await expect(page.getByRole("heading", { name: "Джерела справи" })).toBeVisible();
  await expect(page.getByTitle(/Українська правда/)).toBeVisible();
  const articleArchive = page.locator(".articleArchive");
  await expect(articleArchive.locator(".articleCard")).toBeHidden();
  await articleArchive.getByText("1 матеріал справи").click();
  await expect(articleArchive.locator(".articleCard")).toBeVisible();
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
