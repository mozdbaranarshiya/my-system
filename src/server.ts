import "dotenv/config";
import { createApp, ensureInitialAdmin } from "./app.js";
import { prisma } from "./prisma.js";

const host = process.env.HOST || "127.0.0.1";
const port = Number.parseInt(process.env.PORT || "5000", 10);

async function main() {
  await ensureInitialAdmin();
  const app = createApp();
  const server = app.listen(port, host, () => {
    console.log(`School system listening on http://${host}:${port}`);
  });

  const shutdown = async () => {
    server.close(async () => {
      await prisma.$disconnect();
      process.exit(0);
    });
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

main().catch(async (error) => {
  console.error(error);
  await prisma.$disconnect();
  process.exit(1);
});
