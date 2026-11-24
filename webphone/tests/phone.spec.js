import { test, expect } from "@playwright/test";

test.beforeEach(async ({ context, page }) => {
  // Observe actual WebRTC stats without adding a debug API to the product.
  await context.addInitScript(() => {
    const Native = window.RTCPeerConnection;
    window.__testPeers = [];
    window.RTCPeerConnection = class extends Native {
      constructor(...args) { super(...args); window.__testPeers.push(this); }
    };
  });
  await page.goto("/");
});

async function register(page) {
  await page.getByRole("button", { name: "전화기 연결", exact: true }).click();
  await expect(page.locator("#status")).toHaveText("연결됨");
}

async function mediaStats(page) {
  return page.evaluate(async () => {
    const pc = window.__testPeers.at(-1);
    if (!pc) return { connected: false, sent: 0, received: 0, energy: 0 };
    const report = await pc.getStats();
    let sent = 0, received = 0, energy = 0;
    for (const stats of report.values()) {
      if (stats.kind !== "audio" && stats.mediaType !== "audio") continue;
      if (stats.type === "outbound-rtp") sent += stats.packetsSent || 0;
      if (stats.type === "inbound-rtp") { received += stats.packetsReceived || 0; energy += stats.totalAudioEnergy || 0; }
    }
    return { connected: pc.connectionState === "connected", sent, received, energy };
  });
}

test("initial controls and mobile layout", async ({ page }) => {
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator("#call-router")).toBeDisabled();
  await expect(page.locator("#hangup")).toBeDisabled();
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("inquiry registration, audio, mute and hangup", async ({ page }) => {
  await register(page);
  await page.locator("#call-router").click();
  await expect(page.locator("#status")).toHaveText("통화 중");
  await expect.poll(async () => {
    const stats = await mediaStats(page);
    return stats.connected && stats.sent > 10 && stats.received > 10 && stats.energy > 0;
  }).toBe(true);
  await expect.poll(() => page.locator("#mic-level").evaluate((meter) => meter.value)).toBeGreaterThan(0);
  expect(await page.locator("#remote-audio").evaluate((audio) => !audio.paused)).toBe(true);
  await page.locator("#mute").click();
  await expect(page.locator("#mute")).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => page.locator("#mic-level").evaluate((meter) => meter.value)).toBe(0);
  await page.locator("#mute").click();
  await expect(page.locator("#mute")).toHaveAttribute("aria-pressed", "false");
  await page.locator("#hangup").click();
  await expect(page.locator("#status")).toHaveText("연결됨");
  await expect(page.locator("#call-router")).toBeEnabled();
});

test("inquiry prompt, caller audio, silence and remote hangup", async ({ page }) => {
  await register(page);
  await page.locator("#call-router").click();
  await expect(page.locator("#status")).toHaveText("통화 중");
  await expect.poll(async () => (await mediaStats(page)).energy).toBeGreaterThan(0);
  // The fixture speaks a Korean repair inquiry, then falls silent.
  await expect(page.locator("#status")).toHaveText("연결됨", { timeout: 30000 });
  await expect(page.locator("#events")).toContainText("통화가 종료되었습니다.");
  const transcript = page.locator("#transcript");
  await expect(transcript).toContainText("세탁기");
  await expect(transcript).toContainText("수리");
  await expect(transcript).not.toContainText("상담사");
});

test("hanging up during speech discards the partial inquiry", async ({ page }) => {
  await register(page);
  await page.locator("#call-router").click();
  await expect(page.locator("#status")).toHaveText("통화 중");
  // The greeting is 6.963s and the microphone starts its inquiry at 8s.
  await page.waitForTimeout(8800);
  await page.locator("#hangup").click();
  await expect(page.locator("#status")).toHaveText("연결됨");
  await expect(page.locator("#transcript")).toContainText("완료된 녹음이 없습니다");
});

test("microphone denial is recoverable", async ({ page, context }) => {
  await context.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => { throw new DOMException("Denied", "NotAllowedError"); };
  });
  await page.reload();
  await register(page);
  await page.locator("#call-router").click();
  await expect(page.locator("#error")).toContainText("마이크 권한이 거부되었습니다");
  await expect(page.locator("#status")).toHaveText("연결됨");
  await expect(page.locator("#call-router")).toBeEnabled();
});

test("local credentials are uncached and foreign hosts/origins are refused", async ({ request }) => {
  const config = await request.get("/config.json");
  expect(config.headers()["cache-control"]).toContain("no-store");
  expect((await config.json()).username).toBe("1002");
  expect((await request.get("/config.json", { headers: { Host: "foreign.example" } })).status()).toBe(403);
  expect((await request.get("/ws", { headers: { Origin: "https://foreign.example" } })).status()).toBe(403);
});

test("cancel while microphone access is pending", async ({ page, context }) => {
  await context.addInitScript(() => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (...args) => {
      await new Promise((resolve) => { window.__allowTestMicrophone = resolve; });
      return original(...args);
    };
  });
  await page.reload();
  await register(page);
  await page.locator("#call-router").click();
  await expect.poll(() => page.evaluate(() => Boolean(window.__allowTestMicrophone))).toBe(true);
  await page.locator("#hangup").click();
  await page.evaluate(() => window.__allowTestMicrophone());
  await expect(page.locator("#status")).toHaveText("연결됨");
  await page.waitForTimeout(1500);
  await expect(page.locator("#status")).toHaveText("연결됨");
  expect(await page.evaluate(() => window.__testPeers.every((pc) => pc.connectionState === "closed"))).toBe(true);
});
