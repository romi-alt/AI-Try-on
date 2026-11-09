import * as Sentry from "@sentry/nextjs";
import { sentryOptions } from "@/lib/sentryOptions";

Sentry.init(sentryOptions(process.env.NEXT_PUBLIC_SENTRY_DSN));
