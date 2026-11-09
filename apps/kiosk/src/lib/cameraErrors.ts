/** A shopper-readable reason for a `getUserMedia` failure. */
export function describeCameraError(e: unknown): string {
  const name = e instanceof DOMException || (e && typeof e === "object" && "name" in e) ? String((e as { name: string }).name) : "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return "The camera is blocked. Ask a team member to allow camera access for this screen.";
    case "NotFoundError":
    case "DevicesNotFoundError":
      return "No camera was found on this screen.";
    case "NotReadableError":
    case "TrackStartError":
      return "The camera is being used by something else.";
    case "AbortError":
      return "The camera stopped unexpectedly. Please try again.";
    default:
      return "The camera couldn't start. Please try again, or ask a team member.";
  }
}

export const CAMERA_CONSTRAINTS: MediaStreamConstraints = {
  // Prefer Full HD: the photo is cut from it and the sharper it is the better the try-on. `ideal` means a camera that
  // cannot do 1920x1080 still starts, at whatever it can do.
  video: { width: { ideal: 1920 }, height: { ideal: 1080 }, facingMode: "user" },
  audio: false,
};
