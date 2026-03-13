import { Storage } from "@google-cloud/storage";
import { http, type HttpFunction } from "@google-cloud/functions-framework";
import { GCS_BUCKET, SA_KEY_FILE, SIGNED_URL_EXPIRY_MS, REQUEST_TIMEOUT_MS } from "./constants";

const getServiceAccountKey: HttpFunction = async (req, res) => {
  req.setTimeout(REQUEST_TIMEOUT_MS);
  res.setTimeout(REQUEST_TIMEOUT_MS);

  const storage = new Storage();
  const bucket = storage.bucket(GCS_BUCKET);
  const gcsFile = bucket.file(SA_KEY_FILE);

  const [exists] = await gcsFile.exists();
  if (!exists) {
    res.status(404).send(`Not found: ${SA_KEY_FILE}`);
    return;
  }

  const [signedUrl] = await gcsFile.getSignedUrl({
    action: "read",
    expires: Date.now() + SIGNED_URL_EXPIRY_MS,
  });

  res.set("Cache-Control", "no-store, no-cache, must-revalidate");
  res.redirect(301, signedUrl);
};

http("getServiceAccountKey", getServiceAccountKey);
