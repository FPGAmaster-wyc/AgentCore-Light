(function () {
  const SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0";
  const CHARACTERISTIC_UUID = "12345678-1234-5678-1234-56789abcdef1";
  const DEVICE_FILTERS = [
    { namePrefix: "AgentCore-Light" },
    { namePrefix: "SignalLight-C3" }
  ];

  class AgentBleClient {
    constructor() {
      this.device = null;
      this.server = null;
      this.service = null;
      this.characteristic = null;
      this.onDisconnected = null;
      this.handleDisconnected = this.handleDisconnected.bind(this);
    }

    isSupported() {
      return typeof navigator !== "undefined" && !!navigator.bluetooth;
    }

    async requestDevice() {
      if (!this.isSupported()) {
        throw new Error("当前浏览器不支持 Web Bluetooth");
      }

      this.device = await navigator.bluetooth.requestDevice({
        filters: DEVICE_FILTERS,
        optionalServices: [SERVICE_UUID]
      });

      this.device.removeEventListener("gattserverdisconnected", this.handleDisconnected);
      this.device.addEventListener("gattserverdisconnected", this.handleDisconnected);
      return this.device;
    }

    async connect(device) {
      if (device) {
        this.device = device;
      }

      if (!this.device) {
        await this.requestDevice();
      }

      this.server = await this.device.gatt.connect();
      this.service = await this.server.getPrimaryService(SERVICE_UUID);
      this.characteristic = await this.service.getCharacteristic(CHARACTERISTIC_UUID);
      return this.characteristic;
    }

    async ensureConnected() {
      if (this.characteristic && this.server?.connected) {
        return this.characteristic;
      }
      return this.connect();
    }

    async sendStatus(status) {
      const characteristic = await this.ensureConnected();
      const payload = JSON.stringify({ status });
      const bytes = new TextEncoder().encode(payload);
      await characteristic.writeValueWithoutResponse(bytes);
    }

    disconnect() {
      if (this.device?.gatt?.connected) {
        this.device.gatt.disconnect();
      }
      this.server = null;
      this.service = null;
      this.characteristic = null;
    }

    async getKnownDevices() {
      if (!this.isSupported() || !navigator.bluetooth.getDevices) {
        return [];
      }
      return navigator.bluetooth.getDevices();
    }

    handleDisconnected() {
      this.server = null;
      this.service = null;
      this.characteristic = null;
      if (typeof this.onDisconnected === "function") {
        this.onDisconnected(this.device);
      }
    }
  }

  window.AgentBleClient = AgentBleClient;
  window.AGENT_SIGNAL_LIGHT_BLE = {
    SERVICE_UUID,
    CHARACTERISTIC_UUID,
    DEVICE_FILTERS
  };
})();
