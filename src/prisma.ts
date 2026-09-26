import "dotenv/config";
import { PrismaPg } from "@prisma/adapter-pg";
import { PrismaClient } from "../generated/prisma/client.js";

const connectionString = process.env.DATABASE_URL;
if (!connectionString) {
  throw new Error("DATABASE_URL تنظیم نشده است. فایل .env را بر اساس .env.example تکمیل کنید.");
}

const adapter = new PrismaPg({ connectionString });

export const prisma = new PrismaClient({ adapter });
