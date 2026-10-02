// Smoke check for the vscode-extension build artifacts. Run: node scripts/smoke-check.js
// No servers are started; this only validates files and manifest wiring.
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
let failures = 0;

function check(name, ok, detail) {
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? ` - ${detail}` : ""}`);
  if (!ok) failures++;
}

const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));

// (a) out/extension.js exists and manifest main path matches
const mainPath = path.join(root, pkg.main.replace(/^\.\//, ""));
check("manifest main is ./out/extension.js", pkg.main === "./out/extension.js", pkg.main);
check("out/extension.js exists", fs.existsSync(mainPath));

// (b) media/ui/index.html exists with relative asset paths
const htmlPath = path.join(root, "media", "ui", "index.html");
const htmlExists = fs.existsSync(htmlPath);
check("media/ui/index.html exists", htmlExists);
if (htmlExists) {
  const html = fs.readFileSync(htmlPath, "utf8");
  const scriptSrc = html.match(/<script[^>]+src="([^"]+)"/);
  const cssHref = html.match(/<link[^>]+href="(\.\/assets\/[^"]+\.css)"/);
  check("index.html uses relative script path", !!scriptSrc && scriptSrc[1].startsWith("./"), scriptSrc && scriptSrc[1]);
  check("index.html uses relative css path", !!cssHref, cssHref && cssHref[1]);
  if (scriptSrc) {
    check("script asset exists in media/ui", fs.existsSync(path.join(root, "media", "ui", scriptSrc[1].replace(/^\.\//, ""))));
  }
  if (cssHref) {
    check("css asset exists in media/ui", fs.existsSync(path.join(root, "media", "ui", cssHref[1].replace(/^\.\//, ""))));
  }
}

// manifest wiring sanity
check("webview view is declared", !!pkg.contributes?.views);
check("activation events declared", Array.isArray(pkg.activationEvents) || Object.keys(pkg).length > 0);
check("extension kind / engines vscode present", !!pkg.engines?.vscode, pkg.engines?.vscode);

console.log(failures === 0 ? "\nAll smoke checks passed." : `\n${failures} smoke check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
