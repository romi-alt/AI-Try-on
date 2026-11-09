export type CropRect = { sx: number; sy: number; sw: number; sh: number };

/**
 * The largest centred crop of a `srcW` x `srcH` frame with the given width/height ratio.
 * A landscape webcam frame becomes a portrait slice from the middle.
 */
export function centeredCrop(srcW: number, srcH: number, aspect = 3 / 4): CropRect {
  if (srcW / srcH > aspect) {
    const sw = Math.round(srcH * aspect);
    return { sx: Math.round((srcW - sw) / 2), sy: 0, sw, sh: srcH };
  }
  const sh = Math.round(srcW / aspect);
  return { sx: 0, sy: Math.round((srcH - sh) / 2), sw: srcW, sh };
}

/**
 * Grabs the current video frame as a portrait JPEG. The frame is NOT mirrored (the preview is, to feel like a
 * mirror) so the model sees the shopper the right way round.
 */
export function captureFrame(
  video: HTMLVideoElement,
  opts: { width: number; height: number; quality: number },
): Promise<Blob> {
  if (video.readyState < 2 || !video.videoWidth || !video.videoHeight) {
    return Promise.reject(new Error("The camera isn't ready yet."));
  }
  const canvas = document.createElement("canvas");
  canvas.width = opts.width;
  canvas.height = opts.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return Promise.reject(new Error("Couldn't take the photo in this browser."));

  const { sx, sy, sw, sh } = centeredCrop(video.videoWidth, video.videoHeight, opts.width / opts.height);
  ctx.drawImage(video, sx, sy, sw, sh, 0, 0, opts.width, opts.height);
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("Couldn't take the photo."))),
      "image/jpeg",
      opts.quality,
    ),
  );
}
