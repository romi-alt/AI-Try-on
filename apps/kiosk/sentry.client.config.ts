import * as Sentry from "@sentry/nextjs";
import { sentryOptions } from "@/lib/sentryOptions";

// No Replay integration, on purpose: a recording of the screen would contain the shopper's face.
Sentry.init(sentryOptions(process.env.NEXT_PUBLIC_SENTRY_DSN));
