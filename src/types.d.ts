import "express-session";
import type { CurrentUser, FlashMessage } from "./domain.js";

declare module "express-session" {
  interface SessionData {
    userId?: number;
    csrfToken?: string;
    flash?: FlashMessage[];
  }
}

declare global {
  namespace Express {
    interface Request {
      currentUser?: CurrentUser;
    }
  }
}

export {};
