import { Storage } from "@google-cloud/storage";
import { http, type HttpFunction } from "@google-cloud/functions-framework";

const GCS_BUCKET = "ww-migration-arkhai-installer-files";
const TARBALL_NAME = "market-cli.tar.gz";
const SIGNED_URL_EXPIRY_MS = 15 * 60 * 1000; // 15 minutes

const REQUEST_TIMEOUT_MS = 60 * 1000; // 60 seconds

const downloadMarketCli: HttpFunction = async (req, res) => {
  req.setTimeout(REQUEST_TIMEOUT_MS);
  res.setTimeout(REQUEST_TIMEOUT_MS);
  const version = req.query.version as string | undefined;

  const storage = new Storage();
  const bucket = storage.bucket(GCS_BUCKET);

  // No params → return the install.sh script
  // With version param → return the versioned .tar.gz
  const gcsPath = version
    ? `releases/${version}/${TARBALL_NAME}`
    : "install.sh";

  console.log(gcsPath);

  const file = bucket.file(gcsPath);

  const [exists] = await file.exists();
  if (!exists) {
    res.status(404).send(`Not found: ${gcsPath}`);
    return;
  }

  const [signedUrl] = await file.getSignedUrl({
    action: "read",
    expires: Date.now() + SIGNED_URL_EXPIRY_MS,
  });

  res.redirect(301, signedUrl);
};

http("downloadMarketCli", downloadMarketCli);
