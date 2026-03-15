import sqlite3
import logging
from werkzeug.security import generate_password_hash # Importa para hash de senha de teste

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# ====================================================================
# DADOS DO NOVO MESTRE DE PROFESSORES E DISCIPLINAS
# ====================================================================

mapeamento_professores_disciplinas = {
    'Antónia Helena K.': ['Matemática I'],
    'Albert Calie': ['Álgebra Linear', 'Cálculo Numérico'],
    'Jorge Chantic': ['Introdução à Programação'],
    'João N.': ['Física I'],
    'Maria do Céu C.': ['Inglês Técnico I'],
    'David Ciloni Jackson': ['Ética e Deontologia', 'Sistemas Operacionais', 'Redes de Computadores II'],
    'António Vicente P.': ['Língua Portuguesa I', 'Matemática II', 'Engenharia de Software I', 'Inteligência Artificial', 'Auditoria Informática'],
    'Armindo Vicente P.': ['Cultura Geral', 'Cálculo em Múltiplas Dimensões', 'Física II', 'Engenharia de Software II', 'Engenharia de Software III'],
    'Daniel Ciloni': ['Estrutura de Dados', 'Estatística Aplicada', 'Base de Dados II', 'Economia'],
    # ATENÇÃO: Segurança Informática e Tópicos em Sistemas Operacionais foram transferidos
    # totalmente para 'Inocência Mendes' para evitar conflito de unicidade.
    'Inocência Mendes': ['Redes de Computadores', 'Segurança Informática', 'Tópicos em Sistemas Operacionais'],
    'Olga Vera Peres': ['Base de Dados I', 'Organização Empresarial', 'Comunicação de Dados'],
    'A. Pascual Cashianga': ['Economia Política II'],
    'Davis Gabriel Jackson': ['Sistemas Distribuídos'],
    'José Chantic': ['Tecnologias de Programação da Web I'],
    'Isabel Vasconcelos Cândida': ['Investigação Operacional'],
    # TFC e TEP podem ter co-docência, então dividiremos entre eles
    'Edgar Valente Torres': ['Trabalho de Fim de Curso'], 
    'Deyvid Labahan Grilhas': ['Tópicos Específicos de Profissional'] 
}

# Dados da Grade Curricular (para criação das Ofertas)
grade_informatica = {
    '1º Ano': ['Matemática I', 'Álgebra Linear', 'Introdução à Programação', 'Física I', 'Inglês Técnico I', 'Ética e Deontologia', 'Língua Portuguesa I', 'Cultura Geral'],
    '2º Ano': ['Matemática II', 'Estrutura de Dados', 'Sistemas Operacionais', 'Cálculo em Múltiplas Dimensões', 'Redes de Computadores', 'Base de Dados I', 'Estatística Aplicada', 'Economia Política II', 'Física II'],
    '3º Ano': ['Engenharia de Software I', 'Redes de Computadores II', 'Sistemas Distribuídos', 'Inteligência Artificial', 'Cálculo Numérico', 'Base de Dados II', 'Economia', 'Tecnologias de Programação da Web I'],
    '4º Ano': ['Engenharia de Software II', 'Auditoria Informática', 'Engenharia de Software III', 'Segurança Informática', 'Organização Empresarial', 'Investigação Operacional', 'Tópicos em Sistemas Operacionais', 'Comunicação de Dados'],
    '5º Ano': ['Trabalho de Fim de Curso', 'Tópicos Específicos de Profissional']
}

# Parâmetros da Oferta
curso_nome = 'Informática'
semestre_alvo = 1
periodos_alvo = ['Regular', 'Pós-Laboral']


def init_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        logging.info("--- PASSO 0: LIMPEZA TOTAL DAS TABELAS DE GESTÃO E ASSOCIAÇÃO ---")
        
        # Excluir tabelas de associação (ordem inversa de dependência)
        cursor.execute("DROP TABLE IF EXISTS credenciais_professores;")
        cursor.execute("DROP TABLE IF EXISTS professor_oferta;") 
        cursor.execute("DROP TABLE IF EXISTS professor_curso;")
        cursor.execute("DROP TABLE IF EXISTS oferta_disciplina;")
        cursor.execute("DROP TABLE IF EXISTS disciplinas;")
        cursor.execute("DROP TABLE IF EXISTS professores;")
        
        # Limpar registros de entrada que podem fazer referência a IDs inexistentes
        cursor.execute("UPDATE entradas SET disciplina_id = NULL, professor_id = NULL;")

        logging.info("Tabelas de gestão (Professores, Disciplinas, Ofertas) excluídas e entradas limpas.")

        
        # ====================================================================
        # 1. RECRIAR ESTRUTURAS DE DADOS (COM A CORREÇÃO DE UNICIDADE)
        # ====================================================================
        logging.info("--- PASSO 1: Recriando Estruturas (Com Regra de Unicidade) ---")
        
        # 1.1 Tabela de Disciplinas (Mestre)
        cursor.execute('''
            CREATE TABLE disciplinas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE
            );
        ''')

        # 1.2 Tabela de Professores (Mestre)
        cursor.execute('''
            CREATE TABLE professores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL
            );
        ''')
        
        # 1.3 Tabela de Credenciais
        cursor.execute('''
            CREATE TABLE credenciais_professores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                professor_id INTEGER UNIQUE NOT NULL,
                usuario TEXT UNIQUE NOT NULL,
                senha_hash TEXT NOT NULL,
                
                FOREIGN KEY (professor_id) REFERENCES professores (id)
            );
        ''')

        # 1.4 Tabela de Oferta/Grade (Com Período)
        cursor.execute('''
            CREATE TABLE oferta_disciplina (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                disciplina_id INTEGER NOT NULL,
                curso TEXT NOT NULL,
                ano_frequencia TEXT NOT NULL,
                semestre INTEGER NOT NULL,
                periodo TEXT NOT NULL,
                
                FOREIGN KEY (disciplina_id) REFERENCES disciplinas (id),
                UNIQUE (disciplina_id, curso, ano_frequencia, semestre, periodo)
            );
        ''')
        
        # 1.5 Tabela de Associação Professor <-> Curso (N:M)
        cursor.execute('''
            CREATE TABLE professor_curso (
                professor_id INTEGER,
                curso TEXT NOT NULL,
                
                FOREIGN KEY (professor_id) REFERENCES professores (id),
                PRIMARY KEY (professor_id, curso)
            );
        ''')
        
        # 1.6 Tabela de Associação Professor <-> Oferta (CORREÇÃO DE UNICIDADE APLICADA AQUI)
        cursor.execute('''
            CREATE TABLE professor_oferta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                professor_id INTEGER NOT NULL,
                oferta_id INTEGER NOT NULL UNIQUE,   
                
                FOREIGN KEY (professor_id) REFERENCES professores (id),
                FOREIGN KEY (oferta_id) REFERENCES oferta_disciplina (id)
            );
        ''')
        
        
        # ====================================================================
        # 2. POPULAR COM DADOS DA GRADE E PROFESSORES
        # ====================================================================
        logging.info("--- PASSO 2: Inserindo Mestre de Professores ---")
        
        todos_professores = set(mapeamento_professores_disciplinas.keys())
        professores_para_inserir = [(nome,) for nome in todos_professores]
        cursor.executemany("INSERT INTO professores (nome) VALUES (?)", professores_para_inserir)
        conn.commit()
        logging.info(f"✅ {len(todos_professores)} Professores mestres inseridos.")
        
        # Obter IDs dos professores
        professores_ids = {row['nome']: row['id'] for row in cursor.execute("SELECT id, nome FROM professores").fetchall()}
        
        # Inserir credencial de teste para um professor (ex: David Ciloni Jackson)
        david_id = professores_ids.get('David Ciloni Jackson')
        if david_id:
            cursor.execute('''
                INSERT OR IGNORE INTO credenciais_professores (professor_id, usuario, senha_hash)
                VALUES (?, ?, ?)
            ''', (david_id, 'prof.david', generate_password_hash('123456')))
            logging.info("ℹ️ Credencial de teste 'prof.david' criada.")
            

        logging.info("--- PASSO 3: Inserindo Disciplinas e Ofertas ---")
        
        # 3.1 Inserir todas as Disciplinas na tabela 'disciplinas'
        todas_disciplinas = set()
        for disciplinas_do_ano in grade_informatica.values():
            todas_disciplinas.update(disciplinas_do_ano)

        disciplinas_para_inserir = [(nome,) for nome in todas_disciplinas]
        cursor.executemany("INSERT OR IGNORE INTO disciplinas (nome) VALUES (?)", disciplinas_para_inserir)
        conn.commit()
        logging.info(f"✅ {len(todas_disciplinas)} Disciplinas únicas inseridas.")

        # Obter um dicionário {nome: id} para uso posterior
        disciplinas_ids = {row['nome']: row['id'] for row in cursor.execute("SELECT id, nome FROM disciplinas").fetchall()}

        # 3.2 Inserir as Ofertas na tabela 'oferta_disciplina'
        ofertas_inseridas = 0
        for ano_frequencia, disciplinas in grade_informatica.items():
            for periodo in periodos_alvo:
                for disciplina_nome in disciplinas:
                    disciplina_id = disciplinas_ids.get(disciplina_nome)
                    
                    if disciplina_id:
                        cursor.execute('''
                            INSERT INTO oferta_disciplina (disciplina_id, curso, ano_frequencia, semestre, periodo)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (disciplina_id, curso_nome, ano_frequencia, semestre_alvo, periodo))
                        ofertas_inseridas += 1
        conn.commit()
        logging.info(f"✅ {ofertas_inseridas} Ofertas de Disciplinas (Turmas) criadas.")

        # Obter todas as ofertas para o mapeamento
        ofertas_raw = cursor.execute('''
            SELECT 
                od.id AS oferta_id, 
                d.nome AS nome_disciplina,
                od.periodo
            FROM oferta_disciplina od
            INNER JOIN disciplinas d ON od.disciplina_id = d.id
            WHERE od.curso = ? AND od.semestre = ?
        ''', (curso_nome, semestre_alvo)).fetchall()
        
        # Estrutura para busca rápida: {disciplina_nome: {periodo: [oferta_id]}}
        ofertas_map = {}
        for oferta in ofertas_raw:
            nome = oferta['nome_disciplina']
            periodo = oferta['periodo']
            if nome not in ofertas_map:
                ofertas_map[nome] = {'Regular': [], 'Pós-Laboral': []}
            ofertas_map[nome][periodo].append(oferta['oferta_id'])


        logging.info("--- PASSO 4: Criando Associações Professor <-> Curso e Professor <-> Oferta ---")
        
        associacoes_oferta_count = 0
        
        for prof_nome, disciplinas_atuacao in mapeamento_professores_disciplinas.items():
            prof_id = professores_ids.get(prof_nome)
            
            if not prof_id:
                continue

            # 4.1 Associa o Curso de Atuação (Informática)
            cursor.execute('''
                INSERT OR IGNORE INTO professor_curso (professor_id, curso) VALUES (?, ?)
            ''', (prof_id, curso_nome))

            # 4.2 Associa as Ofertas (Onde a regra de unicidade é importante)
            for disciplina_nome in disciplinas_atuacao:
                if disciplina_nome in ofertas_map:
                    for periodo in periodos_alvo:
                        oferta_ids = ofertas_map[disciplina_nome][periodo]
                        
                        for oferta_id in oferta_ids:
                            try:
                                # O INSERT falhará (IntegrityError) se a oferta_id já estiver na tabela!
                                cursor.execute('''
                                    INSERT INTO professor_oferta (professor_id, oferta_id)
                                    VALUES (?, ?)
                                ''', (prof_id, oferta_id))
                                associacoes_oferta_count += 1
                            except sqlite3.IntegrityError as e:
                                # Isto é esperado se o mapeamento falhar, mas com o mapeamento 
                                # corrigido, deve ocorrer apenas para as disciplinas TFC/TEP 
                                # se tivessem dois professores e fossem a mesma disciplina (corrigido acima).
                                logging.warning(f"⚠️ Conflito de Unicidade em Oferta: {disciplina_nome} ({periodo}) já associada. (Prof: {prof_nome})")

                else:
                    logging.warning(f"Oferta de disciplina '{disciplina_nome}' não encontrada para associação.")

        conn.commit()
        logging.info(f"✅ Total de {associacoes_oferta_count} Associações Professor <-> Oferta criadas com sucesso.")

        
        # Adicionar admin padrão se não existir
        admin_data = cursor.execute("SELECT * FROM administradores WHERE usuario = 'admin'").fetchone()
        if not admin_data:
            cursor.execute('''
                INSERT INTO administradores (usuario, senha) 
                VALUES (?, ?)
            ''', ('admin', generate_password_hash('admin123')))
            logging.info("ℹ️ Usuário 'admin' com senha 'admin123' (hash) criado.")
        
        # Garante que o estado do banco de dados está correto no final
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        logging.error(f"Ocorreu um erro fatal durante a inicialização do DB: {e}")
        raise

    finally:
        conn.close()
        logging.info("🎉 Configuração do banco de dados concluída com sucesso!")
        
# A função init_db() deve ser chamada na inicialização do app para garantir as tabelas
# e pode ser chamada separadamente para realizar a limpeza e repopulação.
if __name__ == '__main__':
    # Código de inicialização para tabelas base (Estudantes, Funcionários, etc.)
    # Se você tiver um código para criar essas tabelas, ele deve vir aqui.
    
    # Executa a limpeza e recriação das tabelas de gestão
    init_db()