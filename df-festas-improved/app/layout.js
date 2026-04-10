import { Inter } from 'next/font/google'
import './globals.css'
import Header from '@/components/Header'
import Footer from '@/components/Footer'

const inter = Inter({ subsets: ['latin'] })

export const metadata = {
  title: 'DF Festas - Espaço completo com piscina para sua festa',
  description: 'Piscina, churrasqueira, pula-pula, som, Wi-Fi, área coberta e descoberta. Tudo pronto para aniversários, confraternizações e eventos em Rio de Janeiro – RJ.',
}

export default function RootLayout({ children }) {
  return (
    <html lang="pt-BR">
      <body className={`${inter.className} bg-gradient-to-b from-primary-50 to-white text-gray-900`}>
        <Header />
        <main className="min-h-screen">
          {children}
        </main>
        <Footer />
      </body>
    </html>
  )
}