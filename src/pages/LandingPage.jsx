import { useCallback, useEffect, useState } from "react";
import Header from "../components/landing/Header.jsx";
import Hero from "../components/landing/Hero.jsx";
import Story from "../components/landing/Story.jsx";
import Services from "../components/landing/Services.jsx";
import Process from "../components/landing/Process.jsx";
import Contact from "../components/landing/Contact.jsx";
import Footer from "../components/landing/Footer.jsx";
import ChatWidget from "../components/landing/ChatWidget.jsx";
import LeadModal from "../components/landing/LeadModal.jsx";
import ContactModal from "../components/landing/ContactModal.jsx";

const CHAT_VISITOR_KEY = "ak-chat-visitor-id";

function createChatVisitorId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return "v-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}

function clearSharedChatStorage() {
  try {
    ["chat-history", "chatHistory", "ak-chat-history", "ak-chat-messages"].forEach(
      (key) => {
        localStorage.removeItem(key);
      }
    );
  } catch (_) {}
}

function initVisitorId() {
  clearSharedChatStorage();
  try {
    let id = sessionStorage.getItem(CHAT_VISITOR_KEY);
    if (!id) {
      id = createChatVisitorId();
      sessionStorage.setItem(CHAT_VISITOR_KEY, id);
    }
    return id;
  } catch (_) {
    return createChatVisitorId();
  }
}

export default function LandingPage() {
  const [visitorId] = useState(initVisitorId);
  const [leadOrder, setLeadOrder] = useState(null);
  const [contactOpen, setContactOpen] = useState(false);

  const leadOpen = Boolean(leadOrder);

  useEffect(() => {
    document.title = "Aigerim Kabaeva — AI Creator";
  }, []);

  useEffect(() => {
    const open = leadOpen || contactOpen;
    document.body.classList.toggle("modal-open", open);
    return () => document.body.classList.remove("modal-open");
  }, [leadOpen, contactOpen]);

  const openLead = useCallback((order) => {
    setContactOpen(false);
    setLeadOrder(order);
  }, []);

  const closeLead = useCallback(() => {
    setLeadOrder(null);
  }, []);

  const openContact = useCallback(() => {
    setContactOpen(true);
  }, []);

  const closeContact = useCallback(() => {
    setContactOpen(false);
  }, []);

  return (
    <>
      <Header onContactOpen={openContact} />
      <main id="top">
        <Hero />
        <Story />
        <Services onOpenLead={openLead} visitorId={visitorId} />
        <Process />
        <Contact onOpenLead={openLead} visitorId={visitorId} />
      </main>
      <Footer onOpenLead={openLead} visitorId={visitorId} />
      <ChatWidget visitorId={visitorId} onOpenLead={openLead} />
      <ContactModal
        open={contactOpen}
        onClose={closeContact}
        onOpenLead={openLead}
        visitorId={visitorId}
      />
      <LeadModal open={leadOpen} order={leadOrder} onClose={closeLead} />
    </>
  );
}
