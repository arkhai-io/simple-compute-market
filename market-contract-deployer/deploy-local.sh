mkdir -p /app/shared-env &&
python3 /app/deploy_alkahest.py &&
npm run deploy:anvil 2>&1 | tee /tmp/deploy.log &&
IDENTITY_ADDR=$(grep 'IdentityRegistry deployed to:' /tmp/deploy.log | awk '{print $$NF}') &&
echo IDENTITY_REGISTRY_ADDRESS=$IDENTITY_ADDR > $ENV_FILE &&
echo REPUTATION_REGISTRY_ADDRESS=0x8004bd8daB57f14Ed299135749a5CB5c42d341BF >> $ENV_FILE &&
echo VALIDATION_REGISTRY_ADDRESS=0x8004C269D0A5647E51E121FeB226200ECE932d55 >> $ENV_FILE &&
echo Wrote contract addresses to $ENV_FILE &&
cat $ENV_FILE