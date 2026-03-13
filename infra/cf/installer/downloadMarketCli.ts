import { Storage } from "@google-cloud/storage";
import { http, type HttpFunction } from "@google-cloud/functions-framework";
import { GCS_BUCKET, TARBALL_NAME, SIGNED_URL_EXPIRY_MS, REQUEST_TIMEOUT_MS } from "./constants";

const downloadMarketCli: HttpFunction = async (req, res) => {
  req.setTimeout(REQUEST_TIMEOUT_MS);
  res.setTimeout(REQUEST_TIMEOUT_MS);
  const version = req.query.version as string | undefined;
  const file = req.query.file as string | undefined;

  const storage = new Storage();
  const bucket = storage.bucket(GCS_BUCKET);

  // No params → return the install.sh script
  // With version param → return the versioned .tar.gz
  // With version + file=checksum → return the .sha256
  let gcsPath: string;
  if (version) {
    const filename =
      file === "checksum" ? `${TARBALL_NAME}.sha256` : TARBALL_NAME;
    gcsPath = `releases/${version}/${filename}`;
  } else {
    gcsPath = "install.sh";
  }

  const gcsFile = bucket.file(gcsPath);

  const [exists] = await gcsFile.exists();
  if (!exists) {
    res.status(404).send(`Not found: ${gcsPath}`);
    return;
  }

  const [signedUrl] = await gcsFile.getSignedUrl({
    action: "read",
    expires: Date.now() + SIGNED_URL_EXPIRY_MS,
  });

  res.set("Cache-Control", "no-store, no-cache, must-revalidate");
  res.redirect(301, signedUrl);
};

http("downloadMarketCli", downloadMarketCli);
