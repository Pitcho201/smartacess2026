import sqlite3
import random
import datetime
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

DB_NAME = 'database.db'
NUM_FUNCIONARIOS = 5

# Listas de dados fictícios para funcionários
FUNCOES = ["Administrativo", "Técnico de TI", "Coordenador", "Recepcionista", "Segurança"]
DEPARTAMENTOS = ["Administração", "Informática", "Acadêmico", "Geral"]

NOMES_MASCULINOS = ["Ricardo", "Paulo", "Afonso", "Tiago", "Sérgio", "Hugo"]
NOMES_FEMININOS = ["Patrícia", "Carla", "Diana", "Vânia", "Elisa", "Sandra"]
SOBRENOMES = ["Ferreira", "Lopes", "Rodrigues", "Monteiro", "Neves", "Teixeira", "Ribeiro", "Correia"]
LETRAS_BI = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def gerar_nome_completo():
    """Gera um nome completo aleatório."""
    primeiro_nome = random.choice(NOMES_MASCULINOS + NOMES_FEMININOS)
    sobrenome1 = random.choice(SOBRENOMES)
    sobrenome2 = random.choice(SOBRENOMES)
    while sobrenome1 == sobrenome2:
        sobrenome2 = random.choice(SOBRENOMES)
    
    return f"{primeiro_nome} {sobrenome1} {sobrenome2}"

def gerar_numero_bi():
    """Gera um número de BI no formato BI[9 números][1 letra] para garantir unicidade."""
    parte_numerica = str(random.randint(100000000, 999999999))
    letra = random.choice(LETRAS_BI)
    
    return f"BI{parte_numerica}{letra}" 


def gerar_funcionarios_teste():
    conn = get_db_connection()
    cursor = conn.cursor()

    logging.info(f"Iniciando a geração de {NUM_FUNCIONARIOS} funcionários de teste...")

    try:
        funcionarios_inseridos_count = 0
        
        for i in range(NUM_FUNCIONARIOS):
            nome = gerar_nome_completo()
            funcao = random.choice(FUNCOES)
            departamento = random.choice(DEPARTAMENTOS)
            
            # Tentar gerar um BI único (tenta até 10 vezes)
            numero_bi = ""
            bi_unico = False
            for attempt in range(10):
                numero_bi = gerar_numero_bi()
                # Verifica se o BI já existe na tabela de funcionários
                cursor.execute("SELECT COUNT(*) FROM funcionarios WHERE numero_bi = ?", (numero_bi,))
                if cursor.fetchone()[0] == 0:
                    bi_unico = True
                    break
            
            if not bi_unico:
                logging.error(f"  ❌ Falha crítica: Não foi possível gerar um BI único para funcionário após 10 tentativas. Pulando.")
                continue
            
            # Inserir funcionário
            try:
                cursor.execute('''
                    INSERT INTO funcionarios (nome, funcao, departamento, numero_bi)
                    VALUES (?, ?, ?, ?)
                ''', (nome, funcao, departamento, numero_bi))
                
                funcionarios_inseridos_count += 1
                logging.info(f"  ✅ Funcionário '{nome}' ({funcao} - {departamento}) registrado (BI: {numero_bi}).")
                
            except sqlite3.IntegrityError:
                logging.warning(f"  ⚠️ Erro de integridade (duplicação de BI). Pulando.")
            except Exception as e:
                logging.error(f"  ❌ Erro ao registrar funcionário {nome}: {e}")
                conn.rollback() 
                continue
        
        conn.commit()
        logging.info(f"\n🎉 Geração de funcionários de teste concluída. Total de {funcionarios_inseridos_count} funcionários inseridos.")

    except Exception as e:
        conn.rollback()
        logging.error(f"Ocorreu um erro geral: {e}")
        
    finally:
        conn.close()
        logging.info("Conexão com o banco de dados fechada.")

if __name__ == '__main__':
    # Recomendado: Executar 'limpar_dados_cadastrais.py' antes para evitar duplicação de BI.
    gerar_funcionarios_teste()