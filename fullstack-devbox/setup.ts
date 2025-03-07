// setup.ts (updated)
import { MorphCloudClient } from 'morphcloud';
import { writeFileSync } from 'fs';
import path from 'path';

// Create necessary files locally first
const indexHtml = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Todo App</title>
  <style>
    body {
      font-family: system-ui, sans-serif;
      max-width: 600px;
      margin: 0 auto;
      padding: 20px;
    }
    h1 {
      color: #333;
    }
    input[type="text"] {
      padding: 8px;
      width: 70%;
      margin-right: 10px;
    }
    button {
      padding: 8px 16px;
      background-color: #4CAF50;
      color: white;
      border: none;
      cursor: pointer;
    }
    ul {
      list-style-type: none;
      padding: 0;
    }
    li {
      padding: 10px;
      border-bottom: 1px solid #eee;
      display: flex;
      align-items: center;
    }
    .completed {
      text-decoration: line-through;
      color: #888;
    }
  </style>
</head>
<body>
  <h1>Todo App</h1>
  <div id="error" style="color: red;"></div>
  
  <form id="todoForm">
    <input type="text" id="newTodo" placeholder="Add a new todo" required>
    <button type="submit">Add</button>
  </form>

  <ul id="todoList">
    <li>Loading todos...</li>
  </ul>

  <script type="module" src="./app.js"></script>
</body>
</html>`;

const appJs = `// Fetch all todos
async function fetchTodos() {
  try {
    document.getElementById('todoList').innerHTML = '<li>Loading todos...</li>';
    
    const response = await fetch('/api/todos');
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || 'Failed to fetch todos');
    }
    
    const todos = await response.json();
    const todoList = document.getElementById('todoList');
    
    todoList.innerHTML = '';
    
    if (todos.length === 0) {
      todoList.innerHTML = '<li>No todos yet</li>';
      return;
    }
    
    todos.forEach(todo => {
      const li = document.createElement('li');
      li.dataset.id = todo.id;
      if (todo.completed) li.classList.add('completed');
      li.textContent = todo.title;
      todoList.appendChild(li);
    });
    
    document.getElementById('error').textContent = '';
  } catch (err) {
    document.getElementById('error').textContent = err.message || 'Error loading todos';
    document.getElementById('todoList').innerHTML = '<li>Failed to load todos</li>';
    console.error('Error loading todos:', err);
  }
}

// Add a new todo
document.getElementById('todoForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  
  const input = document.getElementById('newTodo');
  const title = input.value.trim();
  
  if (!title) return;
  
  try {
    const response = await fetch('/api/todos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title })
    });
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || 'Failed to add todo');
    }
    
    input.value = '';
    fetchTodos();
    document.getElementById('error').textContent = '';
  } catch (err) {
    document.getElementById('error').textContent = err.message || 'Error adding todo';
    console.error('Error adding todo:', err);
  }
});

// Load todos when page loads
document.addEventListener('DOMContentLoaded', fetchTodos);

// Enable HMR
if (import.meta.hot) {
  import.meta.hot.accept(() => {
    console.log("App updated via HMR");
    fetchTodos();
  });
}`;

const serverTs = `import { sql } from "bun";
import App from "./index.html";

// Create table if it doesn't exist
await sql\`
  CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TEXT NOT NULL
  )
\`;

console.log("Table created/exists, starting server...");

Bun.serve({
  port: 3000,
  routes: {
    // Serve the HTML frontend with HMR
    "/*": App,

    // List todos
    "/api/todos": {
      GET: async () => {
        try {
          console.log("Fetching todos");
          const todos = await sql\`SELECT * FROM todos ORDER BY created_at DESC\`;
          console.log(\`Found \${todos.length} todos\`);
          return Response.json(todos);
        } catch (error) {
          console.error("Error fetching todos:", error);
          return new Response(JSON.stringify({ error: "Failed to fetch todos" }), {
            status: 500,
            headers: { "Content-Type": "application/json" }
          });
        }
      },

      // Create todo 
      POST: async (req) => {
        try {
          const todo = await req.json();
          
          if (!todo.title) {
            return new Response(JSON.stringify({ error: "Title is required" }), {
              status: 400,
              headers: { "Content-Type": "application/json" }
            });
          }
          
          const id = crypto.randomUUID();
          const completed = false;
          const created_at = new Date().toISOString();

          console.log("Inserting todo:", { id, title: todo.title, completed, created_at });
          
          await sql\`
            INSERT INTO todos (id, title, completed, created_at)
            VALUES (\${id}, \${todo.title}, \${completed}, \${created_at})
          \`;
          
          return Response.json({ 
            id, 
            title: todo.title, 
            completed, 
            created_at 
          }, { status: 201 });
        } catch (error) {
          console.error("Error creating todo:", error);
          return new Response(JSON.stringify({ error: "Failed to create todo" }), {
            status: 500,
            headers: { "Content-Type": "application/json" }
          });
        }
      }
    },

    // Get todo by ID
    "/api/todos/:id": async (req) => {
      const todo = await sql\`
        SELECT * FROM todos 
        WHERE id = \${req.params.id}
      \`;

      if (!todo.length) {
        return new Response("Not Found", { status: 404 });
      }

      return Response.json(todo[0]);
    }
  },

  error(error) {
    console.error(error);
    return new Response("Internal Server Error", { status: 500 });
  }
});

console.log("Server running with HMR at http://localhost:3000");`;

// Write files locally
writeFileSync('index.html', indexHtml);
writeFileSync('app.js', appJs);
writeFileSync('server.ts', serverTs);

const client = new MorphCloudClient({
    baseUrl: process.env.MORPH_BASE_URL,
    apiKey: process.env.MORPH_API_KEY,
    verbose: true
});

console.log("Creating bunbox environment...");

let snapshot = await client.snapshots.create({
    vcpus: 1,
    memory: 1024,
    diskSize: 4096,
    digest: "bunbox"
})

// setup bun
snapshot = await snapshot.setup("curl -fsSL https://bun.sh/install | bash");
snapshot = await snapshot.setup("echo 'export PATH=$PATH:/root/.bun/bin' >> /root/.profile");
snapshot = await snapshot.setup("bun upgrade --canary");

// setup docker
snapshot = await snapshot.setup("apt update -y");
snapshot = await snapshot.setup("apt install -y docker.io");
snapshot = await snapshot.setup("systemctl enable docker");
snapshot = await snapshot.setup("systemctl start docker");

// setup local postgres (alpine)
snapshot = await snapshot.setup("docker run -d --name postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:alpine");
// wait for postgres to be ready
snapshot = await snapshot.setup("sleep 5");
snapshot = await snapshot.setup("docker exec postgres pg_isready");

console.log(`snapshot id: ${snapshot.id}`);
console.log(`digest: ${snapshot.digest}`);

// start the snapshot and wait for it to be ready
const instance = await client.instances.start({ snapshotId: snapshot.id });
console.log(`Instance ${instance.id} started. Press Enter to stop the instance."`);
process.on('SIGINT', async () => {
    console.log("\nReceived SIGINT. Stopping instance...");
    await instance.stop();
    process.exit(0);
});

console.log(`${JSON.stringify(instance, null, 2)}`);

await instance.waitUntilReady();
await instance.exposeHttpService("web", 3000);
await instance.exec("mkdir -p app");

await instance.exec("cd app && bun add react react-dom");

const ssh = await instance.ssh();

// Upload all necessary files to the instance
await ssh.putFile("server.ts", "/root/app/server.ts");
await ssh.putFile("index.html", "/root/app/index.html");
await ssh.putFile("app.js", "/root/app/app.js");

// Run the server with HMR enabled
const bunCreate = ssh.exec("POSTGRES_URL=postgres://postgres:postgres@localhost:5432/postgres bun run --hot ./server.ts", [], { 
    cwd: "/root/app", 
    detached: true, 
    onStdout: data => console.log(data.toString()), 
    onStderr: data => console.error(data.toString()) 
});

console.log()
console.log("bunbox is ready!");
console.log()

console.log("The development server is running at:");
const url = instance.networking.httpServices.find(s => s.name === "web").url;
console.log(`${url}`);
console.log()

console.log("To launch claude-code, run the following commands:");
console.log("```bash");
console.log(`ssh ${instance.id}@ssh.cloud.morph.so`)
console.log(`cd app`);
console.log(`bunx @anthropic-ai/claude-code`);
console.log("```");
console.log()

// Wait for user input to stop the instance
console.log("Press Enter to stop the instance.");

process.stdin.setRawMode(true);
process.stdin.resume();
process.stdin.on('data', async (data) => {
    // Stop on Enter key or Ctrl+C
    if (data.toString() === '\r' || data.toString() === '\n' || data[0] === 3) {
        console.log("Stopping instance...");
        await instance.stop();
        process.exit(0);
    }
});
