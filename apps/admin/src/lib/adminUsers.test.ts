import { describe, expect, it } from "vitest";
import { authenticate, parseAdminUsers } from "./adminUsers";
import { hashPassword } from "./password";

const alice = hashPassword("alice-pw");
const bob = hashPassword("bob-pw");
const users = parseAdminUsers(`Alice@Shop.pk=${alice}, bob@shop.pk=${bob} ,broken, =nohash,nobody@x=`);

describe("parseAdminUsers", () => {
  it("keeps valid entries, lower-cases emails, and skips junk", () => {
    expect([...users.keys()].sort()).toEqual(["alice@shop.pk", "bob@shop.pk"]);
    expect(parseAdminUsers(undefined).size).toBe(0);
    expect(parseAdminUsers("").size).toBe(0);
  });
});

describe("authenticate", () => {
  it("signs in the right email and password, ignoring case and spaces in the email", () => {
    expect(authenticate(users, "alice@shop.pk", "alice-pw")).toBe("alice@shop.pk");
    expect(authenticate(users, "  ALICE@shop.pk ", "alice-pw")).toBe("alice@shop.pk");
  });
  it("refuses a wrong password, another user's password and an unknown email", () => {
    expect(authenticate(users, "alice@shop.pk", "nope")).toBeNull();
    expect(authenticate(users, "alice@shop.pk", "bob-pw")).toBeNull();
    expect(authenticate(users, "mallory@shop.pk", "alice-pw")).toBeNull();
    expect(authenticate(users, "", "")).toBeNull();
  });
  it("refuses everyone when nothing is configured", () => {
    expect(authenticate(parseAdminUsers(undefined), "alice@shop.pk", "alice-pw")).toBeNull();
  });
});
