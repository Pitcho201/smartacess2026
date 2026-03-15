import sqlite3
import random
import datetime
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

DB_NAME = 'database.db'
NUM_ESTUDANTES_POR_GRUPO = 5 # 5 por Ano e por Período
CURSO_ALVO = 'Informática'
PERIODOS_ALVO = ['Regular', 'Pós-Laboral']
ANOS_ALVO = ['1º Ano', '2º Ano', '3º Ano', '4º Ano', '5º Ano']

# Lista de nomes fictícios comuns (adaptados para a região)
NOMES_MASCULINOS = ["João", "António", "Manuel", "José", "Pedro", "Francisco", "Alberto", "Carlos", "David", "Edson"]
NOMES_FEMININOS = ["Maria", "Ana", "Helena", "Teresa", "Sofia", "Isabel", "Marta", "Joana", "Paula", "Cláudia"]
SOBRENOMES = ["Silva", "Santos", "Costa", "Almeida", "Pereira", "Gomes", "Sousa", "Martins", "Fernandes", "Carvalho", "Vieira", "Ramos"]
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
    # Garante que os sobrenomes não sejam iguais
    while sobrenome1 == sobrenome2:
        sobrenome2 = random.choice(SOBRENOMES)
    
    return f"{primeiro_nome} {sobrenome1} {sobrenome2}"

def gerar_data_nascimento():
    """Gera uma data de nascimento para garantir a idade entre 18 e 35 anos (em Outubro/2025)."""
    # Usamos o contexto (24/10/2025) para os cálculos de idade
    hoje = datetime.date(2025, 10, 24)
    
    # Idade mínima de 18 anos -> Data Máxima de Nascimento
    data_max = hoje - datetime.timedelta(days=18 * 365.25)
    
    # Idade máxima de 35 anos -> Data Mínima de Nascimento
    data_min = hoje - datetime.timedelta(days=35 * 365.25)
    
    # Gerar data aleatória entre data_min e data_max
    dias_entre = (data_max - data_min).days
    data_nascimento_obj = data_min + datetime.timedelta(days=random.randrange(dias_entre))
    
    return data_nascimento_obj.strftime('%Y-%m-%d') # Formato 'YYYY-MM-DD'

def gerar_numero_bi():
    """Gera um número de BI no formato BI[9 números][1 letra] para garantir unicidade."""
    # 9 dígitos
    parte_numerica = str(random.randint(100000000, 999999999))
    # 1 letra
    letra = random.choice(LETRAS_BI)
    
    return f"BI{parte_numerica}{letra}" 


def gerar_estudantes_teste_simples():
    conn = get_db_connection()
    cursor = conn.cursor()

    logging.info(f"Iniciando a geração de estudantes realistas ({NUM_ESTUDANTES_POR_GRUPO} por grupo) para {CURSO_ALVO}...")

    try:
        estudantes_inseridos_count = 0
        for ano_frequencia in ANOS_ALVO:
            for periodo in PERIODOS_ALVO:
                logging.info(f"\n--- Gerando estudantes para {ano_frequencia} - Período {periodo} ---")
                
                for i in range(NUM_ESTUDANTES_POR_GRUPO):
                    nome = gerar_nome_completo()
                    data_nascimento = gerar_data_nascimento()
                    
                    # Tentar gerar um BI único (tenta até 10 vezes)
                    numero_bi = ""
                    bi_unico = False
                    for attempt in range(10):
                        numero_bi = gerar_numero_bi()
                        cursor.execute("SELECT COUNT(*) FROM estudantes WHERE numero_bi = ?", (numero_bi,))
                        if cursor.fetchone()[0] == 0:
                            bi_unico = True
                            break
                    
                    if not bi_unico:
                        logging.error(f"  ❌ Falha crítica: Não foi possível gerar um BI único após 10 tentativas. Pulando estudante.")
                        continue
                    
                    # Inserir estudante (apenas dados básicos)
                    try:
                        cursor.execute('''
                            INSERT INTO estudantes (nome, data_nascimento, numero_bi, curso, periodo, ano_frequencia)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (nome, data_nascimento, numero_bi, CURSO_ALVO, periodo, ano_frequencia))
                        estudante_id = cursor.lastrowid
                        estudantes_inseridos_count += 1
                        logging.info(f"  ✅ Estudante '{nome}' ({data_nascimento}) registrado (BI: {numero_bi}).")
                        
                        # IMPORTANTE: A lógica de associação de disciplina (M:N) foi removida
                        # para respeitar seu esquema atual.
                        
                    except sqlite3.IntegrityError:
                        logging.warning(f"  ⚠️ Erro de integridade (duplicação de BI). Pulando.")
                    except Exception as e:
                        logging.error(f"  ❌ Erro ao registrar estudante {nome}: {e}")
                        conn.rollback() 
                        continue
        
        conn.commit()
        logging.info(f"\n🎉 Geração de estudantes de teste concluída. Total de {estudantes_inseridos_count} estudantes inseridos.")

    except Exception as e:
        conn.rollback()
        logging.error(f"Ocorreu um erro geral: {e}")
        
    finally:
        conn.close()
        logging.info("Conexão com o banco de dados fechada.")

if __name__ == '__main__':
    # Antes de executar, considere rodar 'limpar_dados_cadastrais.py' para evitar duplicação de BI.
    gerar_estudantes_teste_simples()