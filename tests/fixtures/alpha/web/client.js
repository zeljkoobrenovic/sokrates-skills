// Renders the orders list and keeps the last filter in the browser.
const API = "/api/orders";

async function loadOrders(status) {
  const response = await fetch(API + (status ? "?status=" + status : ""), { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error("orders request failed: " + response.status);
  }
  return response.json();
}

function rememberFilter(status) {
  localStorage.setItem("alpha.filter", status);
}

function subscribe(onOrder) {
  const socket = new WebSocket("wss://" + location.host + "/ws/orders");
  socket.onmessage = (event) => onOrder(JSON.parse(event.data));
  socket.onclose = () => setTimeout(() => subscribe(onOrder), 1000);
}

export { loadOrders, rememberFilter, subscribe };
