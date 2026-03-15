import sqlite3
from werkzeug.security import generate_password_hash

# Conectando ao banco
conn = sqlite3.connect('database.db')
cursor = conn.cursor()

# Deletar todos os administradores
cursor.execute('DELETE FROM administradores')

# Criar novo administrador
novo_usuario = 'admin'
nova_senha = '1234Jpn'  # Você pode mudar aqui para qualquer senha forte
senha_hash = generate_password_hash(nova_senha)

cursor.execute('''
INSERT INTO administradores (usuario, senha)
VALUES (?, ?)
''', (novo_usuario, senha_hash))

conn.commit()
conn.close()

print(f"Novo administrador criado com sucesso.\nUsuário: {novo_usuario}\nSenha: {nova_senha}")
