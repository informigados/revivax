#!/usr/bin/env python3
"""
RevivaX - Sistema de Recuperação de Arquivos
Ponto de entrada principal da aplicação

Uso:
    python main.py              # Inicia servidor web
    python main.py --cli        # Modo CLI (futuro)
    python main.py --version    # Mostra versão
"""

import sys
import os
import platform
import socket
import argparse
import logging
import webbrowser
from pathlib import Path
from threading import Timer, Thread

try:
    from waitress import serve
except ImportError:
    serve = None

# Opcional: Tenta importar pywebview para experiência desktop nativa
try:
    import webview
    WEBVIEW_AVAILABLE = True
except ImportError:
    WEBVIEW_AVAILABLE = False

def find_available_port(host: str, start_port: int) -> int:
    """Encontra uma porta disponível a partir da porta fornecida"""
    port = start_port
    max_attempts = 100
    while port <= 65535 and (port - start_port) < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
                return port
        except OSError:
            port += 1
    raise RuntimeError(f"Nenhuma porta disponível encontrada a partir de {start_port}.")

# Configuração do path
BASE_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(BASE_DIR))

# Imports
from web.app import app, init_managers

# Configuração de logging
def setup_logging():
    """Configura logging do sistema"""
    log_dir = BASE_DIR / 'logs'
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / 'revivax.log'
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)


def print_banner():
    """Imprime banner do sistema"""
    banner = """
    ╔══════════════════════════════════════════════════════════════╗
    ║                                                              ║
    ║   ██████╗ ███████╗██╗   ██╗██╗██╗   ██╗ █████╗ ██╗  ██╗      ║
    ║   ██╔══██╗██╔════╝██║   ██║██║██║   ██║██╔══██╗╚██╗██╔╝      ║
    ║   ██████╔╝█████╗  ██║   ██║██║██║   ██║███████║ ╚███╔╝       ║
    ║   ██╔══██╗██╔══╝  ╚██╗ ██╔╝██║╚██╗ ██╔╝██╔══██║ ██╔██╗       ║
    ║   ██║  ██║███████╗ ╚████╔╝ ██║ ╚████╔╝ ██║  ██║██╔╝ ██╗      ║
    ║   ╚═╝  ╚═╝╚══════╝  ╚═══╝  ╚═╝  ╚═══╝  ╚═╝  ╚═╝╚═╝  ╚═╝      ║
    ║                                                              ║
    ║           Sistema Avançado de Recuperação de Arquivos        ║
    ║                                                              ║
    ║   Versão: 1.0.0                    Modo: Somente Leitura     ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)


def check_requirements():
    """Verifica requisitos do sistema"""
    logger = logging.getLogger(__name__)
    
    # Verifica Python version
    if sys.version_info < (3, 8):
        logger.error("Python 3.8+ é necessário")
        return False
    
    # Verifica diretórios
    required_dirs = ['logs', 'recovered', 'web/templates', 'web/static']
    for dir_name in required_dirs:
        dir_path = BASE_DIR / dir_name
        dir_path.mkdir(parents=True, exist_ok=True)
    
    logger.info("Requisitos verificados com sucesso")
    return True


def open_browser(url: str, delay: float = 2.5):
    """Abre navegador após delay"""
    import threading
    import time
    
    def _open():
        time.sleep(delay)
        try:
            # Trailing slash auxilia navegadores a forçarem a atualização da URL bar (evita about:blank)
            final_url = url if url.endswith('/') else url + '/'
            webbrowser.open_new_tab(final_url)
        except Exception as e:
            logging.getLogger(__name__).warning(f"Não foi possível abrir navegador: {e}")
    
    thread = threading.Thread(target=_open)
    thread.daemon = True
    thread.start()


def main():
    """Função principal"""
    # Configura argumentos
    parser = argparse.ArgumentParser(
        description='RevivaX - Sistema de Recuperação de Arquivos',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
    python main.py              # Inicia servidor web na porta 5000
    python main.py --port 8080  # Inicia na porta 8080
    python main.py --no-browser # Não abre navegador automaticamente
        """
    )
    
    parser.add_argument(
        '--version', 
        action='version', 
        version='%(prog)s 1.0.0'
    )
    
    # Host is now strictly forced to localhost for security (SEC-02)
    host = '127.0.0.1'
    
    parser.add_argument(
        '--port',
        type=int,
        default=5000,
        help='Porta do servidor (padrão: 5000)'
    )
    
    parser.add_argument(
        '--no-browser',
        action='store_true',
        help='Não abre navegador automaticamente'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Modo debug (não use em produção)'
    )

    parser.add_argument(
        '--no-webview',
        action='store_true',
        help='Força a abertura no navegador padrão em vez do WebView nativo'
    )
    
    args = parser.parse_args()
    
    # Setup
    logger = setup_logging()
    print_banner()
    
    if not check_requirements():
        sys.exit(1)
    
    # Resolve porta disponível
    try:
        actual_port = find_available_port(host, args.port)
        if actual_port != args.port:
            logger.info(f"Porta {args.port} em uso. Utilizando porta disponível: {actual_port}")
    except Exception as e:
        logger.error(f"Erro ao checar porta: {e}")
        sys.exit(1)
        
    # Garante smartctl disponível (baixa se necessário) ANTES de iniciar o Flask
    logger.info("Verificando disponibilidade do smartctl...")
    try:
        from core.smartctl_setup import ensure_smartctl, SMARTCTL_LOCAL
        sc_path = ensure_smartctl()
        if sc_path:
            logger.info("smartctl pronto: %s", sc_path)
            print(f"  [SMART] smartctl disponível: {sc_path}")
        else:
            logger.warning("smartctl indisponível — SMART usará PowerShell nativo.")
            print("  [SMART] smartctl não encontrado — usando PowerShell como fallback.")
    except Exception as e:
        logger.debug("Pré-verificação do smartctl falhou (não crítico): %s", e)

    # Inicializa managers
    logger.info("Inicializando RevivaX...")
    try:
        init_managers()
        logger.info("Managers inicializados com sucesso")
    except Exception as e:
        logger.error("Erro ao inicializar: %s", e)
        sys.exit(1)
    
    # URL do servidor
    url = f"http://{host}:{actual_port}"
    
    print(f"\n{'='*60}")
    print(f"  Servidor iniciado em: {url}")
    print(f"  Modo: {'DEBUG' if args.debug else 'PRODUÇÃO'}")
    print(f"{'='*60}\n")
    
    print("  Pressione Ctrl+C para encerrar\n")
    
    # Inicia servidor Flask
    try:
        # Decide como exibir a UI
        if not args.no_browser:
            if WEBVIEW_AVAILABLE and not args.no_webview:
                # Inicia Flask numa thread separada
                def run_flask():
                    app.run(
                        host=host,
                        port=actual_port,
                        debug=args.debug,
                        threaded=True,
                        use_reloader=False,
                    )
                
                flask_thread = Thread(target=run_flask)
                flask_thread.daemon = True
                flask_thread.start()
                
                # Inicia WebView nativo (bloqueante)
                logger.info("Iniciando interface nativa com PyWebView...")
                webview.create_window(
                    "RevivaX - Data Recovery", 
                    url, 
                    width=1200, 
                    height=800,
                    min_size=(800, 600)
                )
                webview.start()
                # Quando a janela fecha, a thread principal encerra
                return
            else:
                # Comportamento antigo: abre navegador padrão
                logger.info(f"O servidor está rodando em {url}")
                open_browser(url, delay=2.5)
                if not args.debug and serve:
                    logger.info("Iniciando servidor WSGI de Produção (Waitress)...")
                    serve(app, host=host, port=actual_port)
                else:
                    app.run(host=host, port=actual_port, debug=args.debug, threaded=True, use_reloader=False)
        else:
            # Apenas servidor
            logger.info(f"O servidor está rodando em {url}")
            if not args.debug and serve:
                logger.info("Iniciando servidor WSGI de Produção (Waitress)...")
                serve(app, host=host, port=actual_port)
            else:
                app.run(host=host, port=actual_port, debug=args.debug, threaded=True, use_reloader=False)
            
    except KeyboardInterrupt:
        print("\n\n  Encerrando RevivaX...")
        logger.info("Servidor encerrado pelo usuário")
    except Exception as e:
        logger.error(f"Erro no servidor: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
