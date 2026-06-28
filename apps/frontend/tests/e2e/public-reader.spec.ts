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
  await expect(page.getByRole("link", { name: "найвідвідуваніші" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByRole("link", { name: "набирають обертів" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "останні оновлення" })).toHaveCount(0);

  await page.getByLabel("Пошук справ").fill("корупційна");
  await page.getByRole("button", { name: "знайти" }).click();
  await expect(page.getByRole("heading", { name: "Корупційна справа для перевірки" })).toBeVisible();
  await expect(page.locator('[data-case-variant="lead"]')).toHaveCount(0);
  await expect(page.locator('[data-case-variant="list"]')).toHaveCount(1);
});

test("reader can page through the Case feed without the featured layout repeating", async ({
  page,
}) => {
  await page.goto("/?sort=popular");

  const pagination = page.getByRole("navigation", { name: "Сторінки" });
  await expect(pagination.getByRole("link", { name: "1", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(pagination.locator(".paginationEllipsis")).toHaveCount(1);
  await expect(pagination.getByRole("link", { name: "9", exact: true })).toBeVisible();
  await pagination.getByRole("link", { name: "2", exact: true }).click();

  await expect(page).toHaveURL(/sort=popular.*page=2/);
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
  await expect(footer.getByText(/Сторінки складаються машинно/)).toBeVisible();
  await expect(footer.getByRole("link", { name: "GitHub ↗" })).toHaveAttribute(
    "href",
    "https://github.com/serpanchyk/shkandal",
  );
  await expect(
    footer.getByRole("link", {
      name: "Маєте ідеї або знайшли ваду? Доєднуйтесь до спільноти у WhatsApp ↗",
    }),
  ).toHaveAttribute("href", "https://chat.whatsapp.com/GKLJlgZ5Fh8Fp4WGc6ThB6");
  await expect(
    footer.getByRole("link", { name: "Розробник: Антон Михальчук ↗" }),
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

test("project transparency footer fits responsive viewports", async ({ page }) => {
  for (const width of [1440, 1024, 768, 430, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/about");

    await expect(page.getByRole("contentinfo")).toBeVisible();
    await expect(page.getByRole("link", { name: "Про Шкандаль" })).toBeVisible();
    await expect(page.getByRole("link", { name: "GitHub ↗" })).toBeVisible();
    await expect(
      page.getByRole("link", {
        name: "Маєте ідеї або знайшли ваду? Доєднуйтесь до спільноти у WhatsApp ↗",
      }),
    ).toBeVisible();

    const layout = await page.evaluate(() => {
      const footer = document.querySelector(".siteFooter");
      const whatsapp = document.querySelector<HTMLAnchorElement>(
        '.footerLinks--secondary a[href^="https://chat.whatsapp.com/"]',
      );

      if (!footer || !whatsapp) {
        throw new Error("Transparency footer is missing expected elements.");
      }

      const footerBox = footer.getBoundingClientRect();
      const whatsappBox = whatsapp.getBoundingClientRect();

      return {
        scrollWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
        footerLeft: footerBox.left,
        footerRight: footerBox.right,
        whatsappLeft: whatsappBox.left,
        whatsappRight: whatsappBox.right,
      };
    });

    expect(layout.scrollWidth).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.footerLeft).toBeGreaterThanOrEqual(0);
    expect(layout.footerRight).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.whatsappLeft).toBeGreaterThanOrEqual(layout.footerLeft);
    expect(layout.whatsappRight).toBeLessThanOrEqual(layout.footerRight);
  }
});

test("reader can inspect Case provenance and navigate to an Entity", async ({ page }) => {
  await page.goto("/cases/e2e-public-case");

  await expect(page.getByRole("heading", { name: "Джерела справи" })).toBeVisible();
  await expect(page.getByTitle(/Українська правда/)).toBeVisible();

  const timelineSection = page.locator("section").filter({ has: page.locator("#timeline-title") });
  const timeline = timelineSection.locator(".sectionDisclosure");
  await expect(timelineSection.locator(".sectionHeading + details > summary")).toHaveText("1 подія");
  await expect(timeline).toHaveAttribute("open", "");
  await expect(timeline.locator(".timelineEvent")).toBeVisible();
  await timeline.locator(":scope > summary").click();
  await expect(timeline.locator(".timelineEvent")).toBeHidden();
  await timeline.locator(":scope > summary").click();

  const articleArchive = page.locator(".articleArchive");
  await expect(
    page.locator("section").filter({ has: page.locator("#articles-title") })
      .locator(".sectionHeading + details > summary"),
  ).toHaveText("1 матеріал справи");
  await expect(articleArchive).not.toHaveAttribute("open", "");
  await expect(articleArchive.locator(".articleCard")).toBeHidden();
  await articleArchive.locator("summary").click();
  const articleCard = articleArchive.locator(".articleCard");
  await expect(articleCard).toBeVisible();
  await expect(articleCard.locator(".articleCardImage--empty")).toBeVisible();

  const otherCases = page.locator(".otherCasesArchive");
  await expect(otherCases.getByRole("link", { name: /Інша справа зі спільним матеріалом/ })).toBeVisible();
  const relatedCaseCard = otherCases.locator('[data-case-variant="compact"]');
  await expect(relatedCaseCard).toHaveCount(1);
  await expect(relatedCaseCard.getByText("Досьє для перевірки похідної навігації між справами.")).toBeVisible();
  await expect(relatedCaseCard.getByText("1 матеріал")).toBeVisible();
  await expect(relatedCaseCard.getByText("0 переглядів")).toBeVisible();
  await expect(relatedCaseCard.getByText(/оновлено/)).toBeVisible();
  const compactLayout = await page.evaluate(() => {
    const article = document.querySelector<HTMLElement>(".articleArchive .articleCard");
    const articleText = article?.querySelector<HTMLElement>("div:nth-child(2)");
    const related = document.querySelector<HTMLElement>('[data-case-variant="compact"]');
    const relatedSummary = related?.querySelector<HTMLElement>(".caseSummary");

    if (!article || !articleText || !related || !relatedSummary) {
      throw new Error("Compact cards are missing.");
    }

    return {
      articleHeight: article.getBoundingClientRect().height,
      articleTextLeft: articleText.getBoundingClientRect().left,
      articleLeft: article.getBoundingClientRect().left,
      relatedHeight: related.getBoundingClientRect().height,
      summaryHeight: relatedSummary.getBoundingClientRect().height,
      summaryLineHeight: Number.parseFloat(getComputedStyle(relatedSummary).lineHeight),
      summaryWhiteSpace: getComputedStyle(relatedSummary).whiteSpace,
    };
  });
  expect(Math.abs(compactLayout.relatedHeight - compactLayout.articleHeight)).toBeLessThanOrEqual(8);
  expect(compactLayout.articleTextLeft - compactLayout.articleLeft).toBeGreaterThan(90);
  expect(compactLayout.summaryHeight).toBeLessThanOrEqual(compactLayout.summaryLineHeight + 1);
  expect(compactLayout.summaryWhiteSpace).toBe("nowrap");
  await expect(
    page.locator("section").filter({ has: page.locator("#other-cases-title") })
      .locator(".sectionHeading + details > summary"),
  ).toHaveText("1 подібна справа");
  await otherCases.locator("summary").click();
  await expect(otherCases.getByRole("link", { name: /Інша справа зі спільним матеріалом/ })).toBeHidden();
  await otherCases.locator("summary").click();

  await page.getByText("1 джерело події").click();
  await expect(
    timeline.getByRole("heading", { name: "Джерельний матеріал для перевірки" }),
  ).toBeVisible();

  const entitiesArchive = page.locator(".entitiesArchive");
  await expect(
    page.locator("section").filter({ has: page.locator("#entities-title") })
      .locator(".sectionHeading + details > summary"),
  ).toHaveText("1 згадана особа або організація");
  await expect(entitiesArchive.getByRole("link", { name: /Тестова особа/ })).toBeVisible();
  await entitiesArchive.locator("summary").click();
  await expect(entitiesArchive.getByRole("link", { name: /Тестова особа/ })).toBeHidden();
  await entitiesArchive.locator("summary").click();
  await expect(entitiesArchive.getByRole("link", { name: /Тестова особа/ })).toBeVisible();
  await page.getByRole("link", { name: /Тестова особа/ }).click();
  await expect(page.getByRole("heading", { name: "Тестова особа" })).toBeVisible();
});

test("Case view is counted once per browser session", async ({ page }) => {
  const viewKey = "shkandal:viewed:e2e-public-case";
  const viewRequests: string[] = [];

  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().includes("/api/cases/e2e-public-case/views")
    ) {
      viewRequests.push(request.url());
    }
  });

  await page.goto("/cases/e2e-public-case");

  await page.waitForFunction(
    (key) => sessionStorage.getItem(key) === "1",
    viewKey,
  );

  await expect.poll(() => viewRequests.length).toBe(1);

  await page.reload();

  await page.waitForLoadState("networkidle");

  expect(viewRequests).toHaveLength(1);
  await expect
    .poll(() => page.evaluate((key) => sessionStorage.getItem(key), viewKey))
    .toBe("1");
});