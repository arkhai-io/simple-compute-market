import { Storage } from "@google-cloud/storage";
import { http, type HttpFunction } from "@google-cloud/functions-framework";
import { GCS_BUCKET, INIT_REVERSE_SSH_FILE, SIGNED_URL_EXPIRY_MS, REQUEST_TIMEOUT_MS } from "./constants";

/**
 * Serves a signed URL redirect to `init-reverse-ssh.sh` stored in GCS.
 * The script, when executed on the target machine, installs ngrok and
 * sets up a reverse SSH tunnel.
 *
 * Usage on the target machine:
 *   curl -fsSL <function-url> | bash
 */
const getInitReverseSSH: HttpFunction = async (req, res) => {
  req.setTimeout(REQUEST_TIMEOUT_MS);
  res.setTimeout(REQUEST_TIMEOUT_MS);

  const storage = new Storage();
  const bucket = storage.bucket(GCS_BUCKET);
  const gcsFile = bucket.file(INIT_REVERSE_SSH_FILE);

  const [exists] = await gcsFile.exists();
  if (!exists) {
    res.status(404).send(`Not found: ${INIT_REVERSE_SSH_FILE}`);
    return;
  }

  const [signedUrl] = await gcsFile.getSignedUrl({
    action: "read",
    expires: Date.now() + SIGNED_URL_EXPIRY_MS,
  });

  res.set("Cache-Control", "no-store, no-cache, must-revalidate");
  res.redirect(301, signedUrl);
};

http("getInitReverseSSH", getInitReverseSSH);
