/** Complete one SOR OAuth popup against the exact API callback origin. */
function openSorAuthorizationPopup(
  url: string,
  expectedOrigin: string,
  expectedVendor: string,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const popup = window.open(
      url,
      "eylo_sor_oauth",
      "width=600,height=720,left=200,top=80",
    );
    if (popup === null) {
      reject(new Error("Popup blocked. Allow popups and try again."));
      return;
    }
    let settled = false;
    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", onMessage);
      window.clearInterval(poll);
      if (error) reject(error);
      else resolve();
    };
    const onMessage = (event: MessageEvent) => {
      if (event.source !== popup || event.origin !== expectedOrigin) return;
      const data = event.data as {
        error?: string;
        ok?: boolean;
        type?: string;
        vendor?: string;
      };
      if (data.type !== "eylo:sor-oauth") return;
      if (data.ok === true && data.vendor !== expectedVendor) return;
      finish(
        data.ok ? undefined : new Error(data.error || "Authorization failed."),
      );
    };
    window.addEventListener("message", onMessage);
    const poll = window.setInterval(() => {
      // The callback commits before notifying this window. Some browsers sever
      // popup messaging across OAuth redirects, so closure remains inconclusive.
      if (popup.closed) finish();
    }, 750);
  });
}

export { openSorAuthorizationPopup };
