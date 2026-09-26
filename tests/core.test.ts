import { describe, expect, it } from "vitest";
import { courseScore, parseScore, urlFor, validNationalId } from "../src/domain.js";
import { hashPassword, verifyPassword } from "../src/security.js";

describe("domain rules", () => {
  it("calculates the course score as the average", () => {
    expect(courseScore("18.00", "16.00")).toBe("17.00");
  });

  it("validates score range", () => {
    expect(parseScore("17.5")).toBe("17.50");
    expect(() => parseScore("21")).toThrow();
  });

  it("validates a ten digit national id", () => {
    expect(validNationalId("1234567890")).toBe(true);
    expect(validNationalId("123")).toBe(false);
  });

  it("builds application URLs", () => {
    expect(urlFor("main.gradebook", { classroom_id: 4, subject_id: 7 })).toBe("/gradebook/4/7");
  });
});

describe("password compatibility", () => {
  it("hashes and verifies scrypt passwords", async () => {
    const hash = await hashPassword("1234567890");
    expect(await verifyPassword("1234567890", hash)).toBe(true);
    expect(await verifyPassword("wrong", hash)).toBe(false);
  });
});
