(function () {
  class DeviceTransport {
    constructor(options = {}) {
      this.mode = options.mode || "serial";
      this.bleClient = options.bleClient || null;
      this.lastSentStatus = "";
    }

    setMode(mode) {
      this.mode = mode || "serial";
      if (this.mode !== "bluetooth") {
        this.lastSentStatus = "";
      }
    }

    isBluetoothMode() {
      return this.mode === "bluetooth";
    }

    async connectBluetooth() {
      if (!this.bleClient) {
        throw new Error("BLE 客户端未初始化");
      }
      await this.bleClient.connect();
    }

    disconnectBluetooth() {
      if (!this.bleClient) {
        return;
      }
      this.bleClient.disconnect();
      this.lastSentStatus = "";
    }

    async sendStatus(status) {
      if (!this.isBluetoothMode()) {
        return;
      }
      if (!this.bleClient?.device?.gatt?.connected) {
        return;
      }
      if (!status || status === this.lastSentStatus) {
        return;
      }
      await this.bleClient.sendStatus(status);
      this.lastSentStatus = status;
    }
  }

  window.DeviceTransport = DeviceTransport;
})();
