import {
  pbkdf2 as pbkdf2Callback,
  randomBytes,
  scrypt as scryptCallback,
  timingSafeEqual
} from "node:crypto";
import { promisify } from "node:util";

const scryptAsync = promisify(scryptCallback);
const pbkdf2Async = promisify(pbkdf2Callback);

async function scryptDigest(
  password: string,
  salt: string,
  n: number,
  r: number,
  p: number,
  length: number
): Promise<Buffer> {
  return (await scryptAsync(password, salt, length, {
    N: n,
    r,
    p,
    maxmem: Math.max(64 * 1024 * 1024, 128 * n * r + 1024 * 1024)
  })) as Buffer;
}

export async function hashPassword(password: string): Promise<string> {
  const salt = randomBytes(12).toString("base64url");
  const digest = await scryptDigest(password, salt, 32768, 8, 1, 64);
  return `scrypt:32768:8:1$${salt}$${digest.toString("hex")}`;
}

export async function verifyPassword(password: string, storedHash: string): Promise<boolean> {
  try {
    const [method, salt, expectedHex] = storedHash.split("$");
    if (!method || !salt || !expectedHex || !/^[0-9a-f]+$/i.test(expectedHex)) return false;
    const expected = Buffer.from(expectedHex, "hex");

    let actual: Buffer;
    if (method.startsWith("scrypt:")) {
      const [, nRaw, rRaw, pRaw] = method.split(":");
      const n = Number(nRaw);
      const r = Number(rRaw);
      const p = Number(pRaw);
      if (![n, r, p].every(Number.isFinite)) return false;
      actual = await scryptDigest(password, salt, n, r, p, expected.length);
    } else if (method.startsWith("pbkdf2:")) {
      const [, digest = "sha256", iterationsRaw = "600000"] = method.split(":");
      const iterations = Number(iterationsRaw);
      if (!Number.isFinite(iterations) || iterations <= 0) return false;
      actual = (await pbkdf2Async(password, salt, iterations, expected.length, digest)) as Buffer;
    } else {
      return false;
    }

    return actual.length === expected.length && timingSafeEqual(actual, expected);
  } catch {
    return false;
  }
}
