import { parseSeconds } from "./config";

/**
 * The privacy notice shown at the mirror and on `/privacy`. One source, so the consent screen, the badge, the full
 * page and the phone page can never disagree.
 *
 * THE WORDING IS PLACEHOLDER COPY. It describes what this software does, but it is not legal advice: the shop must
 * have it reviewed for its country (and for children, signage and any law on biometric or facial data) before use.
 *
 * `NEXT_PUBLIC_PHOTO_RETENTION_MINUTES` must match the API's `CAPTURE_TTL_SECONDS` and `RESULT_TTL_SECONDS`
 * (default 60 minutes). If the API is configured for longer, this text would be wrong.
 */
export const privacyConfig = {
  shopName: process.env.NEXT_PUBLIC_SHOP_NAME?.trim() || "this shop",
  contact: process.env.NEXT_PUBLIC_PRIVACY_CONTACT?.trim() || "",
  retentionMinutes: Math.max(1, Math.round(parseSeconds(process.env.NEXT_PUBLIC_PHOTO_RETENTION_MINUTES, 60))),
  // Who renders the picture, in words a shopper understands ("our try-on service provider" if not set).
  providerName: process.env.NEXT_PUBLIC_TRYON_PROVIDER_NAME?.trim() || "our try-on service provider",
};

export function retentionText(minutes = privacyConfig.retentionMinutes): string {
  if (minutes % 60 === 0) {
    const hours = minutes / 60;
    return hours === 1 ? "one hour" : `${hours} hours`;
  }
  return `${minutes} minutes`;
}

export type PrivacySection = { heading: string; body: string[] };

/** The short version shown on the consent screen and in the pop-up. */
export function privacySummary(): string[] {
  const kept = retentionText();
  return [
    "The camera only turns on after you agree, and only while you are taking your photo.",
    `The photo you take, and the look made from it, are deleted automatically within ${kept}.`,
    "We do not identify you, keep a face scan, or sell or share your photo.",
  ];
}

/** The full notice. */
export function privacySections(): PrivacySection[] {
  const { shopName, providerName, contact } = privacyConfig;
  const kept = retentionText();
  return [
    {
      heading: "What the mirror does",
      body: [
        "You choose clothes, then the mirror shows you wearing them. To do that it uses your camera.",
        "The camera turns on only after you agree on the first screen, and turns off as soon as your photo is taken or you leave. While you stand in front of it, a program on this screen works out whether you are fully in view so it can guide you. That happens on the screen itself; nothing from it is stored or sent anywhere.",
      ],
    },
    {
      heading: "Your photo",
      body: [
        `When you strike the pose, one photo is taken. It is sent over an encrypted connection to ${shopName}'s server and to ${providerName}, which draws the clothes onto it. The finished look comes back to the mirror.`,
        `The photo and the finished look are deleted automatically within ${kept}, even if you walk away. Ending your visit, or leaving the mirror idle, clears them from this screen straight away.`,
        "We do not use your photo to recognise or identify you, we do not build a face scan, and we do not use it to train any system.",
      ],
    },
    {
      heading: "Sending the look to your phone",
      body: [
        `If you scan the code, your phone opens a page with your cart and, for up to ${kept}, a picture of your look. The code stops working after 24 hours. Anyone who has the code can see that page, so do not share it.`,
      ],
    },
    {
      heading: "What we keep",
      body: [
        "Orders you place (the items, sizes, prices and the pickup code) are kept for the shop's records. Requests for a team member to bring an item are kept briefly so staff can deal with them.",
        "We count how the mirror is used (for example how many looks were made, and which items are added to a cart) using a random code made for your visit. It is not linked to your name, your face, your phone or any account, and contains no pictures.",
        "If something goes wrong we receive a technical error report. It never includes your photo.",
      ],
    },
    {
      heading: "Your choices",
      body: [
        "You can stop at any time with Exit, or by walking away. If you would like something deleted sooner than the automatic deletion, or have a question, ask a member of staff" + (contact ? ` or contact ${contact}.` : "."),
      ],
    },
  ];
}
