import { describe, expect, it } from "vitest";
import { privacySections, privacySummary, retentionText } from "./privacy";

describe("retentionText", () => {
  it("says hours when it is a whole number of them, minutes otherwise", () => {
    expect(retentionText(60)).toBe("one hour");
    expect(retentionText(120)).toBe("2 hours");
    expect(retentionText(30)).toBe("30 minutes");
    expect(retentionText(90)).toBe("90 minutes");
  });
});

describe("the privacy notice", () => {
  const all = () => [...privacySummary(), ...privacySections().flatMap((s) => [s.heading, ...s.body])].join("\n");

  it("states the retention period in the summary and the full text", () => {
    expect(privacySummary().join(" ")).toContain("within one hour");
    expect(all()).toContain("within one hour");
  });

  it("says what is collected, who gets the photo, and what is not done with it", () => {
    const text = all();
    expect(text).toMatch(/camera only turns on after you agree/);
    expect(text).toMatch(/sent over an encrypted connection/);
    expect(text).toMatch(/do not (use your photo to recognise|identify|sell)/);
    expect(text).toMatch(/never includes your photo/);
  });

  it("explains the phone code and the anonymous counting", () => {
    const text = all();
    expect(text).toMatch(/code stops working after 24 hours/);
    expect(text).toMatch(/random code made for your visit/);
  });

  it("has a way to ask for something to be deleted sooner", () => {
    expect(all()).toMatch(/ask a member of staff/);
  });
});
