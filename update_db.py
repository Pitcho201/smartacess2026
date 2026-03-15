import sqlite3
import os

# Defina o nome do seu arquivo de banco de dados
DATABASE_FILE = 'database.db' 

def get_db_connection():
    """Cria e retorna a conexão com o banco de dados."""
    if not os.path.exists(DATABASE_FILE):
        print(f"ERRO: O arquivo de banco de dados '{DATABASE_FILE}' não foi encontrado.")
        # Pode querer criar o arquivo ou sair
    
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row # Para acessar colunas por nome
    return conn

def atualizar_tabela_estudantes():
    """Adiciona as novas colunas à tabela estudantes, contornando a limitação do UNIQUE."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        print("A iniciar a atualização da tabela 'estudantes'...")
        
        # --- ETAPA 1: ADICIONAR COLUNAS SIMPLES (sem UNIQUE/NOT NULL) ---
        
        # A coluna 'sexo' já pode ter sido adicionada. Usamos um bloco try/except para continuar.
        try:
            cursor.execute("ALTER TABLE estudantes ADD COLUMN sexo TEXT;")
            print("- Coluna 'sexo' adicionada.")
        except sqlite3.OperationalError as e:
            if 'duplicate column name' in str(e):
                print("- Coluna 'sexo' já existia. Ignorado.")
            else: raise

        # 2. Coluna NUMERO_ESTUDANTE (TEXT) - SEM UNIQUE NESTA FASE
        try:
            cursor.execute("ALTER TABLE estudantes ADD COLUMN numero_estudante TEXT;")
            print("- Coluna 'numero_estudante' adicionada (Temporariamente sem UNIQUE).")
        except sqlite3.OperationalError as e:
            if 'duplicate column name' in str(e):
                print("- Coluna 'numero_estudante' já existia. Ignorado.")
            else: raise

        # 3. Coluna ESTADO_CIVIL (TEXT)
        try:
            cursor.execute("ALTER TABLE estudantes ADD COLUMN estado_civil TEXT;")
            print("- Coluna 'estado_civil' adicionada.")
        except sqlite3.OperationalError as e:
            if 'duplicate column name' in str(e):
                print("- Coluna 'estado_civil' já existia. Ignorado.")
            else: raise

        # 4. Coluna RESIDENCIA_ATUAL (TEXT)
        try:
            cursor.execute("ALTER TABLE estudantes ADD COLUMN residencia_atual TEXT;")
            print("- Coluna 'residencia_atual' adicionada.")
        except sqlite3.OperationalError as e:
            if 'duplicate column name' in str(e):
                print("- Coluna 'residencia_atual' já existia. Ignorado.")
            else: raise
        
        # --- ETAPA 2: ADICIONAR A RESTRIÇÃO UNIQUE SEPARADAMENTE (ÍNDICE) ---
        
        # Cria um índice UNIQUE para a coluna 'numero_estudante'. 
        # NOTA: Isto falhará se já existirem valores duplicados nessa coluna!
        try:
            cursor.execute("CREATE UNIQUE INDEX idx_numero_estudante ON estudantes (numero_estudante);")
            print("- Restrição UNIQUE para 'numero_estudante' adicionada via INDEX.")
        except sqlite3.OperationalError as e:
            if 'index idx_numero_estudante already exists' in str(e):
                print("- Restrição UNIQUE já existia. Ignorado.")
            else: 
                print(f"\n❌ Erro ao adicionar UNIQUE: {e}")
                print("Verifique se não existem valores duplicados na coluna 'numero_estudante'.")
                raise # Re-lança o erro se for outro
                

        conn.commit()
        print("\n✅ Tabela 'estudantes' atualizada com sucesso no banco de dados!")
        print("Todas as colunas foram adicionadas, incluindo a restrição UNIQUE.")

    except Exception as e:
        print(f"\n❌ Ocorreu um erro geral: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    atualizar_tabela_estudantes()